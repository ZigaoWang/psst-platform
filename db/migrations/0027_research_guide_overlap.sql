-- Two research sessions can add the same place; the second guide for it is skipped and reported instead of
-- refusing the whole submission.
SET search_path = psst, public;

CREATE OR REPLACE FUNCTION submit_research(p_token text, p_task text, p_result jsonb, p_prompt text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['worker']);
    task tasks := held_task(run, p_task);
    target_cell text := task.input ->> 'cell';
    entry jsonb;
    story jsonb;
    place_id text;
    new_places text[] := '{}';
    places_by_index text[] := '{}';
    revisions text[] := '{}';
    lead jsonb;
    stories integer := 0;
    guides integer := 0;
    guides_skipped text[] := '{}';
    remaining integer;
    revision_id text;
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
        END IF;
        places_by_index := places_by_index || place_id;
        FOR story IN SELECT value FROM jsonb_array_elements(coalesce(entry -> 'stories', '[]')) LOOP
            revision_id := create_revision(run.id, task.id, NULL, 'story', place_id, task.city_id, NULL, NULL, 'en',
                                           story -> 'body', story -> 'claims', p_result ->> 'rulebook',
                                           'researched in cell ' || target_cell);
            revisions := revisions || revision_id;
            stories := stories + 1;
        END LOOP;
        IF entry ? 'guide' AND EXISTS (SELECT 1 FROM items i WHERE i.place_id = places_by_index[cardinality(places_by_index)]
                                       AND i.type = 'guide' AND i.state <> 'retired') THEN
            guides_skipped := guides_skipped || place_id;  -- another session wrote it first
        ELSIF entry ? 'guide' THEN
            revision_id := create_revision(run.id, task.id, NULL, 'guide', place_id, task.city_id, NULL, NULL, 'en',
                                           entry #> '{guide,body}', entry #> '{guide,claims}', p_result ->> 'rulebook',
                                           'researched in cell ' || target_cell);
            revisions := revisions || revision_id;
            guides := guides + 1;
        END IF;
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
    FOR i IN 1 .. cardinality(revisions) LOOP
        PERFORM advance(run.id, revisions[i]);
    END LOOP;
    RETURN jsonb_build_object('places', cardinality(places_by_index), 'new_places', cardinality(new_places),
                              'stories', stories, 'guides', guides, 'leads_open', remaining,
                              'guides_skipped', to_jsonb(guides_skipped));
END;
$$;
