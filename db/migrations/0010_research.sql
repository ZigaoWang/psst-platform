-- Research (design.md, sections 8.1 and 10): cities and cells, leads, places created by research and resolved by
-- the system worker, and the research task's result.
SET search_path = psst, public;

ALTER TABLE areas ADD COLUMN wikidata_id text CHECK (wikidata_id ~ '^Q[1-9][0-9]*$');
ALTER TABLE areas ADD COLUMN osm_admin_level integer;
CREATE INDEX areas_wikidata_idx ON areas (wikidata_id) WHERE wikidata_id IS NOT NULL;

-- Places -----------------------------------------------------------------------------------------------------

-- A new place from research, pending until the system worker resolves it. A place that is the same Wikidata
-- item or OSM element as a previous place keeps that place's id, so places saved in the app still resolve.
CREATE FUNCTION create_place(p_run text, p_wikidata text, p_osm text, p_kind text, p_size text, p_name text,
                             p_local jsonb) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    existing text;
    legacy legacy_places;
    place_id text;
BEGIN
    SELECT id INTO existing FROM places
    WHERE state <> 'refused' AND ((p_wikidata IS NOT NULL AND wikidata_id = p_wikidata)
                                  OR (p_osm IS NOT NULL AND osm_ref = p_osm)) LIMIT 1;
    IF existing IS NOT NULL THEN
        RETURN existing;
    END IF;
    SELECT * INTO legacy FROM legacy_places
    WHERE ((p_wikidata IS NOT NULL AND wikidata_id = p_wikidata) OR (p_osm IS NOT NULL AND osm_ref = p_osm))
      AND NOT EXISTS (SELECT 1 FROM places p WHERE p.id = legacy_places.id)
    ORDER BY (wikidata_id IS NOT DISTINCT FROM p_wikidata) DESC LIMIT 1;
    place_id := coalesce(legacy.id, new_id('pl'));
    INSERT INTO places (id, kind, size, wikidata_id, osm_ref, created_by_run)
    VALUES (place_id, p_kind, coalesce(p_size, 'medium'), p_wikidata, p_osm, p_run);
    INSERT INTO place_names (place_id, role, lang, name, source) VALUES (place_id, 'display', 'en', btrim(p_name), 'research');
    IF p_local IS NOT NULL AND coalesce(p_local ->> 'name', '') <> '' THEN
        INSERT INTO place_names (place_id, role, lang, name, source)
        VALUES (place_id, 'local', p_local ->> 'lang', btrim(p_local ->> 'name'), 'research');
    END IF;
    IF legacy.id IS NOT NULL THEN
        INSERT INTO place_identity (legacy_id, place_id, kind) VALUES (legacy.id, place_id, 'place') ON CONFLICT DO NOTHING;
        INSERT INTO place_identity (legacy_id, place_id, kind)
        SELECT spot, place_id, 'spot' FROM unnest(legacy.spot_ids) AS spot ON CONFLICT DO NOTHING;
    END IF;
    RETURN place_id;
END;
$$;

-- The system worker's result for one pending place: its coordinate and names, or why it can't be used.
CREATE FUNCTION resolve_place(p_token text, p_place text, p_result jsonb) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    system runs := run_for(p_token, ARRAY['system']);
    place places;
    name jsonb;
BEGIN
    SELECT * INTO place FROM places WHERE id = p_place FOR UPDATE;
    IF place.state <> 'pending' THEN
        RETURN place.state;
    END IF;
    IF p_result ? 'refused' THEN
        UPDATE places SET state = 'refused', state_reason = p_result ->> 'refused' WHERE id = p_place;
        PERFORM retire(system.id, i.id, 'its place was refused: ' || (p_result ->> 'refused'))
        FROM items i WHERE i.place_id = p_place AND i.state <> 'retired' AND i.type <> 'translation';
        UPDATE tasks SET state = 'cancelled', problem = 'the place was refused'
        WHERE place_id = p_place AND state IN ('queued', 'leased');
        RETURN 'refused';
    END IF;
    UPDATE places SET
        geom = ST_SetSRID(ST_MakePoint((p_result ->> 'lon')::float8, (p_result ->> 'lat')::float8), 4326),
        coord_source = p_result ->> 'source',
        coord_ref = p_result ->> 'ref',
        h3_r7 = p_result ->> 'cell',
        -- An item OSM tags the element with, unless another place already has it.
        wikidata_id = coalesce(place.wikidata_id, CASE WHEN NOT EXISTS (
            SELECT 1 FROM places o WHERE o.wikidata_id = p_result ->> 'wikidata' AND o.state <> 'refused')
            THEN p_result ->> 'wikidata' END),
        state = 'active'
    WHERE id = p_place;
    FOR name IN SELECT value FROM jsonb_array_elements(coalesce(p_result -> 'names', '[]')) LOOP
        INSERT INTO place_names (place_id, role, lang, name, source)
        VALUES (p_place, name ->> 'role', name ->> 'lang', name ->> 'name', name ->> 'source')
        ON CONFLICT (place_id, role, lang) DO NOTHING;
    END LOOP;
    RETURN 'active';
END;
$$;

-- Fills in each place's country, region, city, district, and neighborhood from the boundaries: the smallest
-- containing boundary per level, preferring the configured source per country; when no neighborhood contains
-- the place, the nearest one in the same city within reach. `p_rules` comes from the rulebook (places.yaml).
CREATE FUNCTION assign_areas(p_token text, p_places text[], p_rules jsonb) RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    system runs := run_for(p_token, ARRAY['system', 'editor']);
    excluded bigint[] := ARRAY(SELECT jsonb_array_elements_text(p_rules -> 'excluded_areas')::bigint);
    preferred jsonb := coalesce(p_rules -> 'preferred_source', '{}');
    nearest float8 := coalesce((p_rules ->> 'nearest_neighborhood_meters')::float8, 1500);
    updated integer;
BEGIN
    WITH target AS (
        SELECT p.id, p.geom, coalesce(p.country_code, (
                   SELECT a.country_code FROM area_parts ap JOIN areas a ON a.id = ap.area_id
                   WHERE a.level = 'country' AND ap.geom && p.geom AND ST_Intersects(ap.geom, p.geom) LIMIT 1))
               AS country_code
        FROM places p WHERE p.state = 'active' AND p.id = ANY(p_places)
    ),
    hits AS MATERIALIZED (
        SELECT t.id AS place_id, t.country_code, a.id AS area_id, a.level, a.source, a.area_km2
        FROM target t
        JOIN area_parts ap ON ap.geom && t.geom AND ST_Intersects(ap.geom, t.geom)
        JOIN areas a ON a.id = ap.area_id
        WHERE a.id <> ALL(excluded)
    ),
    ranked AS (
        SELECT DISTINCT ON (place_id, level) place_id, level, area_id FROM hits
        ORDER BY place_id, level, (source = coalesce(preferred -> country_code ->> level, 'wof')) DESC, area_km2 ASC
    ),
    chosen AS (
        SELECT t.id AS place_id,
               max(r.area_id) FILTER (WHERE r.level = 'country') AS country_id,
               max(r.area_id) FILTER (WHERE r.level = 'region') AS region_id,
               max(r.area_id) FILTER (WHERE r.level = 'city') AS city_id,
               max(r.area_id) FILTER (WHERE r.level = 'district') AS district_id,
               max(r.area_id) FILTER (WHERE r.level = 'neighborhood') AS neighborhood_id
        FROM target t LEFT JOIN ranked r ON r.place_id = t.id GROUP BY t.id
    ),
    closest AS (
        SELECT c.place_id, n.id AS area_id, n.distance
        FROM chosen c JOIN target t ON t.id = c.place_id JOIN areas ci ON ci.id = c.city_id
        CROSS JOIN LATERAL (
            SELECT a.id, ST_Distance(a.geom::geography, t.geom::geography) AS distance
            FROM areas a
            WHERE a.level = 'neighborhood' AND a.id <> ALL(excluded) AND a.geom && ST_Expand(t.geom, 0.03)
              AND (a.parent_id = c.city_id OR ST_Intersects(ST_PointOnSurface(a.geom), ci.geom))
              AND ST_DWithin(a.geom::geography, t.geom::geography, nearest)
            ORDER BY (a.source = coalesce(preferred -> t.country_code ->> 'neighborhood', a.source)) DESC,
                     ST_Distance(a.geom, t.geom) LIMIT 1
        ) n
        WHERE c.neighborhood_id IS NULL
    )
    UPDATE places p SET
        country_code = coalesce(ca.country_code, p.country_code),
        region_id = c.region_id,
        city_id = c.city_id,
        -- A district named like its city, or covering nearly all of it, adds nothing.
        district_id = CASE WHEN da.name = ci.name OR (da.area_km2 >= 0.9 * ci.area_km2
                                AND ST_Covers(da.geom, ST_PointOnSurface(ci.geom))) THEN NULL
                           ELSE c.district_id END,
        neighborhood_id = coalesce(c.neighborhood_id, n.area_id),
        area_rules = jsonb_build_object(
            'neighborhood', CASE WHEN c.neighborhood_id IS NOT NULL THEN 'containing boundary'
                                 WHEN n.area_id IS NOT NULL THEN 'nearest, ' || round(n.distance) || ' m away'
                                 ELSE 'none' END,
            'assigned_by', system.id, 'assigned_at', now())
    FROM chosen c
    LEFT JOIN closest n ON n.place_id = c.place_id
    LEFT JOIN areas ca ON ca.id = c.country_id
    LEFT JOIN areas ci ON ci.id = c.city_id
    LEFT JOIN areas da ON da.id = c.district_id
    WHERE p.id = c.place_id;
    GET DIAGNOSTICS updated = ROW_COUNT;
    -- An item's city follows its place.
    UPDATE items i SET city_id = coalesce(p.city_id, p.region_id)
    FROM places p WHERE i.place_id = p.id AND p.id = ANY(p_places) AND coalesce(p.city_id, p.region_id) IN (
        SELECT id FROM cities) AND i.city_id IS DISTINCT FROM coalesce(p.city_id, p.region_id);
    RETURN updated;
END;
$$;

-- Sets up a city for research: its area (already loaded from the boundary data), slug, and local languages.
CREATE FUNCTION add_city(p_token text, p_area bigint, p_slug text, p_languages text[], p_order integer) RETURNS bigint
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    system runs := run_for(p_token, ARRAY['system']);
    area areas;
BEGIN
    SELECT * INTO area FROM areas WHERE id = p_area;
    IF NOT FOUND OR area.level NOT IN ('city', 'region') OR area.is_point THEN
        RAISE EXCEPTION 'area % is not a city or region with a boundary', p_area USING ERRCODE = '22023';
    END IF;
    INSERT INTO cities (id, slug, name, country_code, local_languages, research_order)
    VALUES (area.id, p_slug, area.name, area.country_code, coalesce(p_languages, '{}'), p_order)
    ON CONFLICT (id) DO UPDATE SET slug = EXCLUDED.slug, local_languages = EXCLUDED.local_languages,
                                   research_order = EXCLUDED.research_order;
    RETURN area.id;
END;
$$;

-- Cells and leads ---------------------------------------------------------------------------------------------

CREATE FUNCTION plan_cells(p_token text, p_city bigint, p_cells jsonb) RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    system runs := run_for(p_token, ARRAY['system']);
    added integer;
BEGIN
    INSERT INTO research_cells (cell, city_id, geom)
    SELECT value ->> 'cell', p_city, ST_GeomFromText(value ->> 'wkt', 4326) FROM jsonb_array_elements(p_cells)
    ON CONFLICT (cell) DO NOTHING;
    GET DIAGNOSTICS added = ROW_COUNT;
    RETURN added;
END;
$$;

-- Records a cell's leads. Leads found again keep what happened to them; a lead that is already a place is known.
CREATE FUNCTION record_leads(p_token text, p_cell text, p_leads jsonb) RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    system runs := run_for(p_token, ARRAY['system']);
    lead jsonb;
    known text;
    recorded integer := 0;
BEGIN
    FOR lead IN SELECT value FROM jsonb_array_elements(p_leads) LOOP
        SELECT id INTO known FROM places WHERE state = 'active'
          AND ((lead ->> 'wikidata' IS NOT NULL AND wikidata_id = lead ->> 'wikidata')
               OR (lead ->> 'osm' IS NOT NULL AND osm_ref = lead ->> 'osm')) LIMIT 1;
        INSERT INTO leads (id, cell, key, origin, name, wikidata_id, osm_ref, url, what, fame, legacy_place, status,
                           place_id, decided_by, decided_at)
        VALUES (new_id('ld'), p_cell, lead ->> 'key', lead ->> 'origin', lead ->> 'name', lead ->> 'wikidata',
                lead ->> 'osm', lead ->> 'url', lead ->> 'what', (lead ->> 'fame')::integer, lead ->> 'legacy',
                CASE WHEN known IS NULL THEN 'open' ELSE 'known' END, known,
                CASE WHEN known IS NULL THEN NULL ELSE system.id END, CASE WHEN known IS NULL THEN NULL ELSE now() END)
        ON CONFLICT (cell, key) DO UPDATE SET name = EXCLUDED.name, url = coalesce(EXCLUDED.url, leads.url),
            what = coalesce(EXCLUDED.what, leads.what), fame = coalesce(EXCLUDED.fame, leads.fame);
        recorded := recorded + 1;
    END LOOP;
    RETURN recorded;
END;
$$;

-- Queues research for a city's open cells, most wanted first (the caller computes the order).
CREATE FUNCTION queue_research(p_token text, p_cells jsonb) RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    system runs := run_for(p_token, ARRAY['system']);
    entry jsonb;
    queued integer := 0;
BEGIN
    FOR entry IN SELECT value FROM jsonb_array_elements(p_cells) LOOP
        CONTINUE WHEN (SELECT state FROM research_cells WHERE cell = entry ->> 'cell') <> 'open';
        PERFORM enqueue(system.id, 'research_cell',
                        'research_cell:' || (entry ->> 'cell') || ':' || (SELECT passes FROM research_cells
                                                                          WHERE cell = entry ->> 'cell'),
                        jsonb_build_object('cell', entry ->> 'cell'),
                        (SELECT city_id FROM research_cells WHERE cell = entry ->> 'cell'), NULL, NULL, NULL,
                        '{}', NULL, coalesce((entry ->> 'priority')::integer, 0));
        UPDATE research_cells SET state = 'queued' WHERE cell = entry ->> 'cell';
        queued := queued + 1;
    END LOOP;
    RETURN queued;
END;
$$;

-- Research results ------------------------------------------------------------------------------------------

-- Applies a research_cell result: new places (pending until resolved), story angles queued as write_story
-- tasks, guide information queued for every new place, and every lead accounted for. Returns what was done.
CREATE FUNCTION submit_research(p_token text, p_task text, p_result jsonb, p_prompt text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['worker']);
    task tasks := held_task(run, p_task);
    target_cell text := task.input ->> 'cell';
    entry jsonb;
    angle jsonb;
    place_id text;
    new_places text[] := '{}';
    places_by_index text[] := '{}';
    lead jsonb;
    stories integer := 0;
    remaining integer;
BEGIN
    IF task.type <> 'research_cell' THEN
        RAISE EXCEPTION 'task % is not research', p_task USING ERRCODE = '22023';
    END IF;
    FOR entry IN SELECT value FROM jsonb_array_elements(coalesce(p_result -> 'places', '[]')) LOOP
        IF entry ? 'existing' THEN
            place_id := entry ->> 'existing';
            IF NOT EXISTS (SELECT 1 FROM places WHERE id = place_id AND state IN ('pending', 'active')) THEN
                RAISE EXCEPTION 'no place %', place_id USING ERRCODE = '22023';
            END IF;
        ELSE
            place_id := create_place(run.id, entry ->> 'wikidata', entry ->> 'osm', entry ->> 'kind', entry ->> 'size',
                                     entry ->> 'name', entry -> 'local_name');
            IF (SELECT state FROM places WHERE id = place_id) = 'pending' THEN
                new_places := new_places || place_id;
            END IF;
            PERFORM enqueue(run.id, 'write_guide', 'write_guide:' || place_id, '{}', task.city_id, place_id,
                            NULL, NULL);
        END IF;
        places_by_index := places_by_index || place_id;
        FOR angle IN SELECT value FROM jsonb_array_elements(coalesce(entry -> 'angles', '[]')) LOOP
            PERFORM enqueue(run.id, 'write_story', 'write_story:' || place_id || ':' || md5(angle::text),
                            angle || jsonb_build_object('cell', target_cell, 'ordinary', coalesce(entry -> 'ordinary', 'false'))
                            , task.city_id, place_id, NULL, NULL);
            stories := stories + 1;
        END LOOP;
    END LOOP;
    FOR lead IN SELECT value FROM jsonb_array_elements(coalesce(p_result -> 'leads', '[]')) LOOP
        UPDATE leads SET status = lead ->> 'status', reason = lead ->> 'reason',
                         place_id = CASE WHEN lead ->> 'status' = 'added' THEN places_by_index[(lead ->> 'place')::integer + 1]
                                         ELSE coalesce(lead ->> 'existing', leads.place_id) END,
                         decided_by = run.id, decided_at = now()
        WHERE id = lead ->> 'lead' AND leads.cell = target_cell;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'lead % isn''t in cell %', lead ->> 'lead', target_cell USING ERRCODE = '22023';
        END IF;
    END LOOP;
    SELECT count(*) INTO remaining FROM leads l WHERE l.cell = target_cell AND l.status IN ('open', 'later');
    UPDATE research_cells SET passes = passes + 1, last_researched_at = now(), notes = p_result ->> 'notes',
                              state = CASE WHEN remaining = 0 THEN 'researched' ELSE 'open' END
    WHERE research_cells.cell = target_cell;
    IF cardinality(new_places) > 0 THEN
        PERFORM enqueue(run.id, 'resolve_places', 'resolve_places:' || p_task, jsonb_build_object('places', new_places),
                        task.city_id, NULL, NULL, NULL, '{}', NULL, 20);
    END IF;
    UPDATE tasks SET state = 'done', result = p_result, prompt = p_prompt, done_by = run.id, done_at = now(),
                     leased_by = NULL, leased_until = NULL
    WHERE id = task.id;
    RETURN jsonb_build_object('places', cardinality(places_by_index), 'new_places', cardinality(new_places),
                              'stories_queued', stories, 'leads_open', remaining);
END;
$$;

-- Writing waits until its place is resolved (the writer needs the pin and the names). Otherwise as before.
CREATE OR REPLACE FUNCTION lease_task(p_token text, p_types text[], p_city bigint DEFAULT NULL) RETURNS SETOF tasks
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['worker', 'system', 'publisher']);
    task tasks;
BEGIN
    PERFORM expire_leases();
    SELECT t.* INTO task FROM tasks t JOIN task_types y ON y.name = t.type
    WHERE t.state = 'queued' AND t.type = ANY(p_types)
      AND (p_city IS NULL OR t.city_id = p_city)
      AND y.runner = run.kind
      AND (run.kind <> 'worker' OR t.model = run.model)
      AND NOT run.id = ANY(t.exclude_runs)
      AND (t.place_id IS NULL OR t.type NOT IN ('write_story', 'write_guide')
           OR EXISTS (SELECT 1 FROM places p WHERE p.id = t.place_id AND p.state = 'active'))
      AND (t.independence IS NULL OR NOT EXISTS (
            SELECT 1 FROM task_leases l JOIN tasks o ON o.id = l.task_id
            WHERE l.run_id = run.id AND o.independence = t.independence))
    ORDER BY t.priority DESC, t.created_at, t.id
    FOR UPDATE OF t SKIP LOCKED
    LIMIT 1;
    IF NOT FOUND THEN
        RETURN;
    END IF;
    UPDATE tasks SET state = 'leased', leased_by = run.id, attempts = attempts + 1, problem = NULL,
                     leased_until = now() + make_interval(mins => lease_minutes(type))
    WHERE id = task.id RETURNING * INTO task;
    INSERT INTO task_leases (task_id, run_id) VALUES (task.id, run.id);
    RETURN NEXT task;
END;
$$;

-- System tasks other than tool checks are closed with their result here.
CREATE FUNCTION finish_system_task(p_token text, p_task text, p_result jsonb) RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['system']);
    task tasks := held_task(run, p_task);
BEGIN
    UPDATE tasks SET state = 'done', result = p_result, done_by = run.id, done_at = now(), leased_by = NULL,
                     leased_until = NULL
    WHERE id = task.id;
END;
$$;

GRANT EXECUTE ON FUNCTION resolve_place(text, text, jsonb), assign_areas(text, text[], jsonb),
    add_city(text, bigint, text, text[], integer),
    plan_cells(text, bigint, jsonb), record_leads(text, text, jsonb), queue_research(text, jsonb),
    finish_system_task(text, text, jsonb) TO psst_platform_system;
GRANT EXECUTE ON FUNCTION submit_research(text, text, jsonb, text) TO psst_platform_worker;
GRANT EXECUTE ON FUNCTION lease_task(text, text[], bigint)
    TO psst_platform_worker, psst_platform_system, psst_platform_publisher;
SELECT apply_read_grants();
