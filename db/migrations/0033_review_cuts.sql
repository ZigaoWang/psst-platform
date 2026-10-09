-- A good story can still need a cut before it publishes (decision 25): the review names it in `fix`, and the story
-- gets its one revision making only that cut. The mark stays good, so it is compared with the editor's as marked.
SET search_path = psst, public;

CREATE OR REPLACE FUNCTION submit_task(p_token text, p_task text, p_result jsonb, p_prompt text DEFAULT NULL) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['worker', 'system']);
    task tasks := held_task(run, p_task);
    item items;
    claim_ids text[];
    entry record;
    decision jsonb;
    new_revision text;
    decided text[] := '{}';
    outcome jsonb := '{}';
    next jsonb := '{}';
BEGIN
    SELECT * INTO item FROM items WHERE id = task.item_id;
    CASE task.type
    WHEN 'audit' THEN
        claim_ids := ARRAY(SELECT id FROM claims WHERE revision_id = task.revision_id ORDER BY n);
        FOR entry IN SELECT * FROM verdicts_for(p_result, claim_ids) LOOP
            PERFORM record_check(run.id, task.id, task.revision_id, entry.id, 'audit', entry.verdict, entry.note);
        END LOOP;
        PERFORM record_check(run.id, task.id, task.revision_id, NULL, 'audit', p_result #>> '{item,verdict}',
                             p_result #>> '{item,note}', coalesce(p_result -> 'item', '{}'));
    WHEN 'review' THEN
        FOR decision IN SELECT value FROM jsonb_array_elements(coalesce(p_result -> 'decisions', '[]')) LOOP
            IF NOT task.input -> 'revisions' ? (decision ->> 'revision') THEN
                RAISE EXCEPTION 'revision % isn''t in this review', decision ->> 'revision' USING ERRCODE = '22023';
            END IF;
            decided := decided || (decision ->> 'revision');
        END LOOP;
        IF EXISTS (SELECT 1 FROM jsonb_array_elements_text(task.input -> 'revisions') AS r(id)
                   JOIN items i ON i.current_revision = r.id
                   WHERE i.state = 'checking' AND NOT r.id = ANY(decided)) THEN
            RAISE EXCEPTION 'decide every item in the review' USING ERRCODE = '22023';
        END IF;
    WHEN 'check_photo', 'check_translation' THEN
        IF p_result ->> 'verdict' = 'pass' AND jsonb_array_length(coalesce(p_result -> 'untraced', '[]')) > 0 THEN
            RAISE EXCEPTION 'details no claim states fail the check' USING ERRCODE = '22023';
        END IF;
        PERFORM record_check(run.id, task.id, task.revision_id, NULL,
                             CASE WHEN task.type = 'check_translation' THEN 'translation' ELSE 'item' END,
                             p_result ->> 'verdict', p_result ->> 'note', p_result);
    WHEN 'write_trail', 'revise', 'translate' THEN
        new_revision := create_revision(
            run.id, task.id,
            CASE WHEN task.type = 'revise' THEN task.item_id
                 WHEN task.type = 'translate' THEN (SELECT id FROM items WHERE translates = task.item_id
                                                     AND language = p_result ->> 'language' AND state <> 'retired')
            END,
            CASE task.type WHEN 'write_trail' THEN 'trail' WHEN 'translate' THEN 'translation' ELSE item.type END,
            task.place_id, task.city_id,
            CASE WHEN task.type = 'translate' THEN task.item_id END,
            CASE WHEN task.type = 'translate' THEN task.revision_id
                 WHEN task.type = 'revise' AND item.type = 'translation' THEN p_result ->> 'translation_of' END,
            coalesce(p_result ->> 'language', 'en'), p_result -> 'body', coalesce(p_result -> 'claims', '[]'),
            p_result ->> 'rulebook', coalesce(nullif(p_result ->> 'reason', ''), task.type), p_result ->> 'bar');
        outcome := jsonb_build_object('revision', new_revision);
    WHEN 'tool_check' THEN
        IF NOT EXISTS (SELECT 1 FROM checks c WHERE c.task_id = task.id AND c.kind = 'tool') THEN
            RAISE EXCEPTION 'record the tool check before submitting the task' USING ERRCODE = '22023';
        END IF;
    ELSE
        RAISE EXCEPTION 'task type % is submitted through its own command', task.type USING ERRCODE = '22023';
    END CASE;

    UPDATE tasks SET state = 'done', result = p_result, prompt = p_prompt, done_by = run.id, done_at = now(),
                     leased_by = NULL, leased_until = NULL
    WHERE id = task.id;

    IF task.type = 'audit' THEN
        outcome := outcome || jsonb_build_object('audit', settle_audit(run.id, (task.input ->> 'batch')));
    ELSIF task.type = 'review' THEN
        FOR decision IN SELECT value FROM jsonb_array_elements(p_result -> 'decisions') LOOP
            SELECT i.* INTO item FROM items i WHERE i.current_revision = decision ->> 'revision';
            IF NOT FOUND OR item.state <> 'checking' THEN
                CONTINUE;  -- retired meanwhile (its place was refused, for one)
            END IF;
            -- Good publishes, or first gets its one revision making the cut it names; weak gets its one revision
            -- aimed at the reason; bad is dropped.
            PERFORM record_check(run.id, task.id, decision ->> 'revision', NULL, 'review',
                                 CASE WHEN decision ->> 'mark' = 'good' AND decision ->> 'fix' IS NULL
                                      THEN 'pass' ELSE 'fail' END,
                                 coalesce(decision ->> 'fix', decision ->> 'reason'),
                                 jsonb_build_object('mark', decision ->> 'mark', 'reason', decision ->> 'reason',
                                                    'revisable', decision ->> 'mark' <> 'bad'));
            next := next || jsonb_build_object(decision ->> 'revision', advance(run.id, decision ->> 'revision'));
        END LOOP;
        PERFORM plan_review_audit(run.id, task.id);
        outcome := jsonb_build_object('decided', next);
    ELSE
        outcome := outcome || jsonb_build_object('next', advance(run.id, coalesce(new_revision, task.revision_id)));
    END IF;
    RETURN outcome;
END;
$$;

SELECT apply_read_grants();
