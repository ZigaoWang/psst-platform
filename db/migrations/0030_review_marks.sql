-- Review marks each story and guide good, weak, or bad against the golden set (decision 25): good publishes, weak gets
-- one revision aimed at the reason, bad is dropped. Reviewers no longer edit: an edit skipped a second review, and
-- both errors the first audits found were in reviewers' own edits.
SET search_path = psst, public;

-- The editor's marked stories: the calibration examples every review sees, and the set the reviewer must re-mark
-- blind before it gates anything. Content, so only here.
CREATE TABLE golden_stories (
    id         text PRIMARY KEY CHECK (id ~ id_pattern('gs')),
    city_id    bigint REFERENCES cities,
    place      text NOT NULL CHECK (place <> ''),
    headline   text NOT NULL CHECK (headline <> ''),
    short      text NOT NULL CHECK (short <> ''),
    long       text NOT NULL CHECK (long <> ''),
    sources    text NOT NULL CHECK (sources <> ''),
    mark       text NOT NULL CHECK (mark IN ('good', 'weak', 'bad')),
    reason     text NOT NULL CHECK (reason <> ''),
    item_id    text REFERENCES items,
    origin     text NOT NULL CHECK (origin <> ''),
    marked_by  text NOT NULL CHECK (marked_by <> ''),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION evaluate(p_revision text) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    revision revisions;
    item items;
    since timestamptz;
    tool checks;
    verdict checks;
    source_item items;
BEGIN
    SELECT * INTO revision FROM revisions WHERE id = p_revision;
    SELECT * INTO item FROM items WHERE id = revision.item_id;
    IF item.state <> 'checking' OR item.current_revision <> p_revision THEN
        RETURN jsonb_build_object('outcome', 'none', 'reason', 'not being checked');
    END IF;
    since := item.checking_since;

    SELECT * INTO tool FROM checks WHERE revision_id = p_revision AND kind = 'tool' AND created_at >= since
    ORDER BY id DESC LIMIT 1;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('outcome', 'wait', 'missing', 'tool');
    ELSIF tool.verdict = 'fail' THEN
        RETURN jsonb_build_object('outcome', 'revise', 'problems', jsonb_build_array(tool.note), 'details', tool.details);
    END IF;

    IF item.type = 'translation' THEN
        SELECT * INTO source_item FROM items WHERE id = item.translates;
        IF revision.translation_of NOT IN (coalesce(source_item.published_revision, ''), coalesce(source_item.current_revision, ''))
           OR source_item.state NOT IN ('accepted', 'published', 'checking') THEN
            RETURN jsonb_build_object('outcome', 'revise', 'problems',
                                      jsonb_build_array('the text it translates has changed'));
        END IF;
    END IF;

    SELECT * INTO verdict FROM checks
    WHERE revision_id = p_revision AND claim_id IS NULL AND kind = 'editor' AND created_at >= since
    ORDER BY id DESC LIMIT 1;
    IF FOUND THEN
        RETURN CASE WHEN verdict.verdict = 'pass' THEN jsonb_build_object('outcome', 'accept')
                    ELSE jsonb_build_object('outcome', 'reject', 'problems', jsonb_build_array(verdict.note),
                                            'revisable', true) END;
    END IF;

    IF item.type IN ('translation', 'photo') THEN
        SELECT * INTO verdict FROM checks
        WHERE revision_id = p_revision AND claim_id IS NULL AND kind IN ('translation', 'item') AND created_at >= since
        ORDER BY id DESC LIMIT 1;
        IF NOT FOUND THEN
            RETURN jsonb_build_object('outcome', 'wait', 'missing', 'check');
        END IF;
        RETURN CASE WHEN verdict.verdict = 'pass' THEN jsonb_build_object('outcome', 'accept')
                    ELSE jsonb_build_object('outcome', 'revise', 'problems', jsonb_build_array(verdict.note)) END;
    END IF;

    SELECT * INTO verdict FROM checks
    WHERE revision_id = p_revision AND claim_id IS NULL AND kind = 'review' AND created_at >= since
    ORDER BY id DESC LIMIT 1;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('outcome', 'wait', 'missing', 'review');
    ELSIF verdict.verdict = 'pass' THEN
        RETURN jsonb_build_object('outcome', 'accept');
    END IF;
    RETURN jsonb_build_object('outcome', 'reject', 'problems', jsonb_build_array(verdict.note),
                              'revisable', coalesce((verdict.details ->> 'revisable')::boolean, false));
END;
$$;

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
            -- Good publishes; weak gets its one revision aimed at the reason; bad is dropped.
            PERFORM record_check(run.id, task.id, decision ->> 'revision', NULL, 'review',
                                 CASE WHEN decision ->> 'mark' = 'good' THEN 'pass' ELSE 'fail' END,
                                 decision ->> 'reason',
                                 jsonb_build_object('mark', decision ->> 'mark',
                                                    'revisable', decision ->> 'mark' = 'weak'));
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
