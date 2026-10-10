-- Research is submitted place by place (decision 26): each finished place is stored at once and renews the lease,
-- so a session that stops loses at most the place in hand. A lease that runs out gives the cell to the next
-- researcher and ends the stopped session's run; the cell's reviews wait for its final result.
SET search_path = psst, public;

UPDATE settings SET value = '90', note = 'Minutes a research lease lasts; each place submitted renews it.'
WHERE key = 'lease.research_cell';

-- One place of a research result: the place (new or existing), its stories, and its guide unless one exists.
CREATE FUNCTION research_place(p_run text, p_task tasks, p_entry jsonb, p_rulebook text, p_bar text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    place text;
    fresh boolean := false;
    story jsonb;
    written text[] := '{}';
    stories integer := 0;
    guide_skipped boolean := false;
    note text := 'researched in cell ' || (p_task.input ->> 'cell');
BEGIN
    IF p_entry ? 'existing' THEN
        place := p_entry ->> 'existing';
        IF NOT EXISTS (SELECT 1 FROM places WHERE id = place AND state IN ('pending', 'active')) THEN
            RAISE EXCEPTION 'no place %', place USING ERRCODE = '22023';
        END IF;
    ELSE
        place := create_place(p_run, p_entry ->> 'wikidata', p_entry ->> 'osm', p_entry ->> 'kind',
                              p_entry ->> 'size', p_entry ->> 'name', p_entry -> 'local_name');
        fresh := (SELECT state FROM places WHERE id = place) = 'pending';
    END IF;
    FOR story IN SELECT value FROM jsonb_array_elements(coalesce(p_entry -> 'stories', '[]')) LOOP
        written := written || create_revision(p_run, p_task.id, NULL, 'story', place, p_task.city_id, NULL, NULL, 'en',
                                              story -> 'body', story -> 'claims', p_rulebook, note, p_bar);
        stories := stories + 1;
    END LOOP;
    IF p_entry ? 'guide' AND EXISTS (SELECT 1 FROM items i WHERE i.place_id = place AND i.type = 'guide'
                                     AND i.state <> 'retired') THEN
        guide_skipped := true;  -- another session wrote it first
    ELSIF p_entry ? 'guide' THEN
        written := written || create_revision(p_run, p_task.id, NULL, 'guide', place, p_task.city_id, NULL, NULL, 'en',
                                              p_entry #> '{guide,body}', p_entry #> '{guide,claims}', p_rulebook, note,
                                              p_bar);
    END IF;
    RETURN jsonb_build_object('place', place, 'new', fresh, 'revisions', to_jsonb(written), 'stories', stories,
                              'guide', p_entry ? 'guide' AND NOT guide_skipped, 'guide_skipped', guide_skipped);
END;
$$;

-- One finished place, submitted while the researcher works on: stored, its leads marked added, its place resolved,
-- its writing tool checked, and the lease renewed.
CREATE FUNCTION submit_research_place(p_token text, p_task text, p_place jsonb, p_leads jsonb, p_rulebook text,
                                      p_bar text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['worker']);
    task tasks := held_task(run, p_task);
    outcome jsonb;
    lead_id text;
    revision text;
BEGIN
    IF task.type <> 'research_cell' THEN
        RAISE EXCEPTION 'task % is not research', p_task USING ERRCODE = '22023';
    END IF;
    outcome := research_place(run.id, task, p_place, p_rulebook, p_bar);
    FOR lead_id IN SELECT value FROM jsonb_array_elements_text(coalesce(p_leads, '[]')) LOOP
        UPDATE leads SET status = 'added', place_id = outcome ->> 'place', decided_by = run.id, decided_at = now()
        WHERE id = lead_id AND cell = task.input ->> 'cell';
        IF NOT FOUND THEN
            RAISE EXCEPTION 'lead % isn''t in cell %', lead_id, task.input ->> 'cell' USING ERRCODE = '22023';
        END IF;
    END LOOP;
    IF (outcome ->> 'new')::boolean THEN
        PERFORM enqueue(run.id, 'resolve_places', 'resolve_places:' || p_task || ':' || (outcome ->> 'place'),
                        jsonb_build_object('places', jsonb_build_array(outcome ->> 'place')),
                        task.city_id, NULL, NULL, NULL, '{}', NULL, 20);
    END IF;
    FOR revision IN SELECT value FROM jsonb_array_elements_text(outcome -> 'revisions') LOOP
        PERFORM advance(run.id, revision);
    END LOOP;
    UPDATE tasks SET leased_until = now() + make_interval(mins => lease_minutes(type)) WHERE id = task.id;
    RETURN outcome - 'revisions' || jsonb_build_object('written', jsonb_array_length(outcome -> 'revisions'));
END;
$$;

-- The cell's final result: any places not yet submitted, and every lead it still holds accounted for. A lead marked
-- added names the place by its index in this result or, for a place submitted earlier, by its id.
CREATE OR REPLACE FUNCTION submit_research(p_token text, p_task text, p_result jsonb, p_prompt text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['worker']);
    task tasks := held_task(run, p_task);
    target_cell text := task.input ->> 'cell';
    entry jsonb;
    outcome jsonb;
    new_places text[] := '{}';
    places_by_index text[] := '{}';
    revisions text[] := '{}';
    lead jsonb;
    stories integer := 0;
    guides integer := 0;
    guides_skipped text[] := '{}';
    remaining integer;
    first_waiting text;
BEGIN
    IF task.type <> 'research_cell' THEN
        RAISE EXCEPTION 'task % is not research', p_task USING ERRCODE = '22023';
    END IF;
    FOR entry IN SELECT value FROM jsonb_array_elements(coalesce(p_result -> 'places', '[]')) LOOP
        outcome := research_place(run.id, task, entry, p_result ->> 'rulebook', p_result ->> 'bar');
        places_by_index := places_by_index || (outcome ->> 'place');
        IF (outcome ->> 'new')::boolean THEN
            new_places := new_places || (outcome ->> 'place');
        END IF;
        revisions := revisions || ARRAY(SELECT jsonb_array_elements_text(outcome -> 'revisions'));
        stories := stories + (outcome ->> 'stories')::integer;
        guides := guides + CASE WHEN (outcome ->> 'guide')::boolean THEN 1 ELSE 0 END;
        IF (outcome ->> 'guide_skipped')::boolean THEN
            guides_skipped := guides_skipped || (outcome ->> 'place');
        END IF;
    END LOOP;
    FOR lead IN SELECT value FROM jsonb_array_elements(coalesce(p_result -> 'leads', '[]')) LOOP
        UPDATE leads SET status = lead ->> 'status', reason = lead ->> 'reason',
                         place_id = CASE WHEN lead ? 'place' AND lead ->> 'status' = 'added'
                                         THEN places_by_index[(lead ->> 'place')::integer + 1]
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
    FOR i IN 1 .. cardinality(revisions) LOOP
        PERFORM advance(run.id, revisions[i]);
    END LOOP;
    -- Places submitted earlier were waiting for this result; their review can start now.
    SELECT r.id INTO first_waiting FROM revisions r JOIN items i ON i.current_revision = r.id
    WHERE r.created_by_task = task.id AND i.state = 'checking' ORDER BY r.id LIMIT 1;
    IF first_waiting IS NOT NULL THEN
        PERFORM ensure_review(run.id, first_waiting);
    END IF;
    RETURN jsonb_build_object('places', cardinality(places_by_index), 'new_places', cardinality(new_places),
                              'stories', stories, 'guides', guides, 'leads_open', remaining,
                              'guides_skipped', to_jsonb(guides_skipped));
END;
$$;

CREATE OR REPLACE FUNCTION ensure_review(p_run text, p_revision text) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    revision revisions := (SELECT r FROM revisions r WHERE r.id = p_revision);
    batch text[];
    writers text[];
    city bigint;
BEGIN
    IF EXISTS (SELECT 1 FROM tasks WHERE type = 'review' AND state IN ('queued', 'leased')
               AND input -> 'revisions' ? p_revision) THEN
        RETURN NULL;
    END IF;
    -- Research submitted place by place is reviewed together once the cell's final result is in.
    IF EXISTS (SELECT 1 FROM tasks t WHERE t.id = revision.created_by_task AND t.type = 'research_cell'
               AND t.state <> 'done') THEN
        RETURN NULL;
    END IF;
    -- The batch is everything the same task wrote; a revision written outside a task is reviewed on its own.
    SELECT array_agg(r.id ORDER BY r.id), array_agg(DISTINCT r.created_by_run), min(i.city_id)
    INTO batch, writers, city
    FROM revisions r JOIN items i ON i.current_revision = r.id
    WHERE (r.created_by_task = revision.created_by_task OR r.id = p_revision) AND i.state = 'checking'
      AND i.type IN ('story', 'guide', 'trail');
    IF EXISTS (SELECT 1 FROM unnest(batch) AS b(id) WHERE (evaluate(b.id) ->> 'missing') IS DISTINCT FROM 'review') THEN
        RETURN NULL;  -- some item in the submission still waits for its tool check
    END IF;
    RETURN enqueue(p_run, 'review', 'review:' || coalesce(revision.created_by_task, p_revision) || ':' ||
                   floor(extract(epoch FROM clock_timestamp()) * 1000),
                   jsonb_build_object('revisions', to_jsonb(batch)), city, NULL, NULL, NULL, writers, NULL, 10);
END;
$$;

-- A lease that runs out gives the task to the next worker; a worker run left holding nothing ends, since the
-- session behind it has stopped.
CREATE OR REPLACE FUNCTION expire_leases() RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    expired integer;
    stopped text[];
BEGIN
    WITH gone AS (
        UPDATE tasks
        SET state = CASE WHEN attempts >= setting('lease.max_attempts')::text::integer THEN 'failed' ELSE 'queued' END,
            leased_by = NULL, leased_until = NULL, problem = 'the lease ran out; the session that held it stopped'
        FROM (SELECT id, leased_by AS holder FROM tasks WHERE state = 'leased' AND leased_until < now() FOR UPDATE) old
        WHERE tasks.id = old.id
        RETURNING old.holder)
    SELECT count(*), array_agg(DISTINCT holder) INTO expired, stopped FROM gone;
    UPDATE runs SET ended_at = now(), notes = concat_ws('; ', notes, 'ended when its lease ran out')
    WHERE id = ANY(coalesce(stopped, '{}')) AND kind = 'worker' AND ended_at IS NULL
      AND NOT EXISTS (SELECT 1 FROM tasks t WHERE t.leased_by = runs.id AND t.state = 'leased');
    RETURN expired;
END;
$$;

GRANT EXECUTE ON FUNCTION submit_research_place(text, text, jsonb, jsonb, text, text) TO psst_platform_worker;
SELECT apply_read_grants();
