-- Photos (content.md, section 4.3): a worker chooses candidates by their Commons key; the system worker reads each
-- file's record from Commons itself, makes our copies, and creates the photo revision for checking, attributed to
-- the worker who chose it.
SET search_path = psst, public;

INSERT INTO task_types (name, runner, description) VALUES
    ('import_photo', 'system', 'Read a chosen photo''s record from Commons, make our copies, and submit it.');

CREATE FUNCTION submit_photos(p_token text, p_task text, p_result jsonb, p_prompt text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['worker']);
    task tasks := held_task(run, p_task);
    choice jsonb;
    queued integer := 0;
BEGIN
    IF task.type <> 'find_photos' THEN
        RAISE EXCEPTION 'task % is not a photo search', p_task USING ERRCODE = '22023';
    END IF;
    FOR choice IN SELECT value FROM jsonb_array_elements(coalesce(p_result -> 'choices', '[]')) LOOP
        IF coalesce(choice ->> 'key', '') !~ '^commons:File:.+' THEN
            RAISE EXCEPTION 'a photo is chosen by its Commons key' USING ERRCODE = '22023';
        END IF;
        PERFORM enqueue(run.id, 'import_photo', 'import_photo:' || task.place_id || ':' || (choice ->> 'key'),
                        choice || jsonb_build_object('chosen_by', run.id, 'chosen_in', task.id),
                        task.city_id, task.place_id, NULL, NULL, '{}', NULL, 15);
        queued := queued + 1;
    END LOOP;
    UPDATE tasks SET state = 'done', result = p_result, prompt = p_prompt, done_by = run.id, done_at = now(),
                     leased_by = NULL, leased_until = NULL
    WHERE id = task.id;
    RETURN jsonb_build_object('photos_queued', queued);
END;
$$;

-- Called by the system worker once our copies exist: creates the photo item and revision, attributed to the run
-- that chose it, and starts its checks.
CREATE FUNCTION create_photo(p_token text, p_task text, p_body jsonb, p_rulebook text) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    system runs := run_for(p_token, ARRAY['system']);
    task tasks := held_task(system, p_task);
    revision_id text;
BEGIN
    revision_id := create_revision(task.input ->> 'chosen_by', task.id, NULL, 'photo', task.place_id, task.city_id,
                                   NULL, NULL, 'en', p_body, '[]', p_rulebook, 'chosen from Commons');
    PERFORM advance(system.id, revision_id);
    RETURN revision_id;
END;
$$;

GRANT EXECUTE ON FUNCTION submit_photos(text, text, jsonb, text) TO psst_platform_worker;
GRANT EXECUTE ON FUNCTION create_photo(text, text, jsonb, text) TO psst_platform_system;
SELECT apply_read_grants();
