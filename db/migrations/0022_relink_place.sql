-- An editor corrects the Wikidata item a place is linked to. Reading the new item needs the network, so the console
-- queues a system task; the system worker takes the coordinate and names from the new item (as when a place is
-- first resolved) and applies them. The guide was written from the old item, so it goes back to draft with a
-- revision task; its published revision stays live until the new one passes its checks.
SET search_path = psst, public;

INSERT INTO task_types (name, runner, description) VALUES
    ('relink_place', 'system', 'Link a place to the Wikidata item an editor named, and have its guide revised.');

CREATE FUNCTION wikidata_holder(p_place text, p_wikidata text) RETURNS text
LANGUAGE sql STABLE SET search_path = psst, public, pg_temp AS $$
    SELECT id FROM places WHERE wikidata_id = p_wikidata AND state <> 'refused' AND id <> p_place
$$;

CREATE FUNCTION console_relink_place(p_token text, p_place text, p_wikidata text, p_reason text) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run text := console_act(p_token, 'relink place', p_place,
                            jsonb_build_object('wikidata', p_wikidata, 'reason', p_reason));
    place places;
    holder text := wikidata_holder(p_place, p_wikidata);
BEGIN
    IF coalesce(p_wikidata, '') !~ '^Q[1-9][0-9]*$' THEN
        RAISE EXCEPTION 'a Wikidata item looks like Q42' USING ERRCODE = '22023';
    END IF;
    IF coalesce(btrim(p_reason), '') = '' THEN
        RAISE EXCEPTION 'say why the link is wrong' USING ERRCODE = '22023';
    END IF;
    SELECT * INTO place FROM places WHERE id = p_place;
    IF NOT FOUND OR place.state <> 'active' THEN
        RAISE EXCEPTION 'only an active place can be relinked' USING ERRCODE = '22023';
    END IF;
    IF place.wikidata_id IS NOT DISTINCT FROM p_wikidata THEN
        RAISE EXCEPTION 'the place is already linked to %', p_wikidata USING ERRCODE = '22023';
    END IF;
    IF holder IS NOT NULL THEN
        RAISE EXCEPTION '% is already the item of place %', p_wikidata, holder USING ERRCODE = '23505';
    END IF;
    RETURN enqueue(run, 'relink_place', 'relink_place:' || p_place || ':' || p_wikidata,
                   jsonb_build_object('wikidata', p_wikidata, 'reason', btrim(p_reason)),
                   place.city_id, p_place, NULL, NULL, '{}', NULL, 50);
END;
$$;

-- Applies a relink once the system worker has read the new item: p_result has lat, lon, source, ref, cell, and
-- names, as for resolve_place.
CREATE FUNCTION relink_place(p_token text, p_task text, p_result jsonb) RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    system runs := run_for(p_token, ARRAY['system']);
    task tasks := held_task(system, p_task);
    wikidata text := task.input ->> 'wikidata';
    place places;
    holder text := wikidata_holder(task.place_id, wikidata);
    guide items;
    name jsonb;
    problem text;
    sent integer := 0;
BEGIN
    IF holder IS NOT NULL THEN
        RAISE EXCEPTION '% became the item of place % in the meantime', wikidata, holder USING ERRCODE = '23505';
    END IF;
    SELECT * INTO place FROM places WHERE id = task.place_id FOR UPDATE;
    UPDATE places SET
        wikidata_id = wikidata,
        geom = ST_SetSRID(ST_MakePoint((p_result ->> 'lon')::float8, (p_result ->> 'lat')::float8), 4326),
        coord_source = p_result ->> 'source', coord_ref = p_result ->> 'ref', h3_r7 = p_result ->> 'cell'
    WHERE id = place.id;
    -- Names the old item gave are replaced by the new item's; the display name stays as it was chosen.
    DELETE FROM place_names WHERE place_id = place.id AND source = 'wikidata' AND role <> 'display';
    FOR name IN SELECT value FROM jsonb_array_elements(coalesce(p_result -> 'names', '[]')) LOOP
        INSERT INTO place_names (place_id, role, lang, name, source)
        VALUES (place.id, name ->> 'role', name ->> 'lang', name ->> 'name', name ->> 'source')
        ON CONFLICT (place_id, role, lang) DO NOTHING;
    END LOOP;
    problem := format('The place''s Wikidata item was corrected from %s to %s (%s). Rebuild the identifier, About, '
                      'and key facts from the new item, and drop every claim that rests on the old one.',
                      coalesce(place.wikidata_id, 'none'), wikidata, task.input ->> 'reason');
    FOR guide IN SELECT * FROM items WHERE place_id = place.id AND type = 'guide' AND state <> 'retired' LOOP
        IF guide.state <> 'draft' THEN
            PERFORM transition(guide.id, 'draft', system.id, NULL, 'the place''s Wikidata item was corrected');
        END IF;
        PERFORM enqueue(system.id, 'revise', 'revise:relink:' || guide.current_revision || ':' || wikidata,
                        jsonb_build_object('problems', jsonb_build_array(problem)), guide.city_id, place.id,
                        guide.id, guide.current_revision, '{}', NULL, 10);
        sent := sent + 1;
    END LOOP;
    RETURN sent;
END;
$$;

GRANT EXECUTE ON FUNCTION console_relink_place(text, text, text, text) TO psst_platform_console;
GRANT EXECUTE ON FUNCTION relink_place(text, text, jsonb) TO psst_platform_system;
