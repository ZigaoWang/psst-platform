-- The content loop of decision 22 (design.md, section 7): one research session per cell writes every story and
-- guide, the tools check what is mechanical, one review session per submission approves, edits, or rejects each
-- item, a rejected item gets at most one revision, and a random 10 percent audit of each reviewed batch gates
-- publishing. Narrow claim checks, item checks, escalations, and single-item writing tasks are retired.
SET search_path = psst, public;

-- Review verdicts are whole-item verdicts.
ALTER TABLE checks DROP CONSTRAINT checks_kind_check, DROP CONSTRAINT checks_check, DROP CONSTRAINT checks_check1;
ALTER TABLE checks ADD CONSTRAINT checks_kind_check CHECK (kind IN ('tool', 'review', 'audit', 'editor', 'translation',
                                                                    'item', 'claim_a', 'claim_b', 'escalation'));
ALTER TABLE checks ADD CONSTRAINT checks_check CHECK ((claim_id IS NULL) =
    (verdict IN ('pass', 'fail') OR kind IN ('tool', 'item', 'translation', 'review')));
ALTER TABLE checks ADD CONSTRAINT checks_check1 CHECK (kind NOT IN ('tool', 'item', 'translation', 'review')
                                                       OR claim_id IS NULL);

-- Task types that no longer have a job stay for the history of the tasks that used them.
ALTER TABLE task_types ADD COLUMN active boolean NOT NULL DEFAULT true;
INSERT INTO task_types (name, runner, description) VALUES
    ('review', 'worker', 'Approve, edit, or reject each story and guide of one research submission.');
UPDATE task_types SET active = false
WHERE name IN ('write_story', 'write_guide', 'check_claims_a', 'check_claims_b', 'check_item', 'escalate');
UPDATE task_types SET description = 'Research a cell end to end: its places, and every story and guide for them.'
WHERE name = 'research_cell';
UPDATE task_types SET description = 'Write the one revision a rejected story or guide gets.' WHERE name = 'revise';

-- Tokens a run used, recorded by whoever started it, so cost per published place can be measured.
ALTER TABLE runs ADD COLUMN tokens bigint CHECK (tokens >= 0);

-- An audit batch is one review batch's accepted items.
ALTER TABLE audit_batches ADD COLUMN review_task text REFERENCES tasks;
ALTER TABLE audit_batches ALTER COLUMN type DROP NOT NULL;
ALTER TABLE audit_batches DROP CONSTRAINT audit_batches_outcome_check;
ALTER TABLE audit_batches ADD CONSTRAINT audit_batches_outcome_check
    CHECK (outcome IN ('open', 'passed', 'failed', 'superseded'));
CREATE UNIQUE INDEX audit_batches_review_idx ON audit_batches (review_task) WHERE review_task IS NOT NULL;

-- Stories chosen by an editor as the reference for voice and the kind of surprise. Content, so only in the database.
CREATE TABLE style_references (
    id         text PRIMARY KEY CHECK (id ~ id_pattern('sr')),
    city_id    bigint REFERENCES cities,
    place      text NOT NULL CHECK (place <> ''),
    headline   text NOT NULL CHECK (headline <> ''),
    short      text NOT NULL CHECK (short <> ''),
    long       text NOT NULL CHECK (long <> ''),
    look       text,
    why        text NOT NULL CHECK (why <> ''),
    origin     text NOT NULL CHECK (origin <> ''),
    created_at timestamptz NOT NULL DEFAULT now()
);

DELETE FROM settings WHERE key IN ('routing.write_story', 'routing.write_guide', 'routing.check_claims_a',
                                   'routing.check_claims_b', 'routing.check_item', 'routing.escalate',
                                   'audit.min_batch', 'audit.min_sample', 'audit.extra_sample_rate',
                                   'lease.write_story')
   OR key LIKE 'audit.threshold.%';
UPDATE settings SET value = '"claude-sonnet-5-5"' WHERE key IN ('routing.research_cell', 'routing.revise');
INSERT INTO settings (key, value, note) VALUES
    ('routing.review', '"claude-sonnet-5-5"', 'Model for reviewing research submissions.'),
    ('audit.sample_rate', '0.1', 'Share of each reviewed batch''s accepted items audited at random (at least one).'),
    ('lease.review', '120', 'Minutes a review lease lasts.')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, note = EXCLUDED.note;
UPDATE settings SET value = '360' WHERE key = 'lease.research_cell';
DELETE FROM settings WHERE key = 'revise.max_rounds';

-- Leasing reads routing when the task is leased, takes only active types, and holds work on a place (and a review
-- of a new place's writing) until the place is resolved.
CREATE OR REPLACE FUNCTION lease_task(p_token text, p_types text[], p_city bigint DEFAULT NULL) RETURNS SETOF tasks
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['worker', 'system', 'publisher']);
    task tasks;
BEGIN
    PERFORM expire_leases();
    SELECT t.* INTO task FROM tasks t JOIN task_types y ON y.name = t.type
    WHERE t.state = 'queued' AND t.type = ANY(p_types) AND y.active
      AND (p_city IS NULL OR t.city_id = p_city)
      AND y.runner = run.kind
      AND (run.kind <> 'worker' OR (SELECT value #>> '{}' FROM settings WHERE key = 'routing.' || t.type) = run.model)
      AND NOT run.id = ANY(t.exclude_runs)
      AND (t.place_id IS NULL OR t.type IN ('tool_check', 'resolve_places', 'relink_place')
           OR EXISTS (SELECT 1 FROM places p WHERE p.id = t.place_id AND p.state = 'active'))
      AND (t.type <> 'review' OR NOT EXISTS (
            SELECT 1 FROM jsonb_array_elements_text(t.input -> 'revisions') AS r(id)
            JOIN revisions v ON v.id = r.id JOIN items i ON i.id = v.item_id JOIN places p ON p.id = i.place_id
            WHERE p.state = 'pending'))
      AND (t.independence IS NULL OR NOT EXISTS (
            SELECT 1 FROM task_leases l JOIN tasks o ON o.id = l.task_id
            WHERE l.run_id = run.id AND o.independence = t.independence))
    ORDER BY t.priority DESC, t.created_at, t.id
    FOR UPDATE OF t SKIP LOCKED
    LIMIT 1;
    IF NOT FOUND THEN
        RETURN;
    END IF;
    UPDATE tasks SET state = 'leased', leased_by = run.id, model = coalesce(run.model, model),
                     attempts = attempts + 1, problem = NULL,
                     leased_until = now() + make_interval(mins => lease_minutes(type))
    WHERE id = task.id RETURNING * INTO task;
    INSERT INTO task_leases (task_id, run_id) VALUES (task.id, run.id);
    RETURN NEXT task;
END;
$$;

-- Where a revision stands. Stories, guides, and trails need a passing tool check and a review (a revision written by
-- a review is its edit and needs no second review); translations and photos keep their own check.
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

    IF EXISTS (SELECT 1 FROM tasks WHERE id = revision.created_by_task AND type = 'review') THEN
        RETURN jsonb_build_object('outcome', 'accept');
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

-- Queues the review of a research submission (or of a single revision) once every item in it has passed its tool
-- check. Revisions already in an open review are left alone.
CREATE FUNCTION ensure_review(p_run text, p_revision text) RETURNS text
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

-- Plans the audit of a settled review batch: 10 percent of its accepted items (at least one), at random.
CREATE FUNCTION plan_review_audit(p_run text, p_review text) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    review tasks := (SELECT t FROM tasks t WHERE t.id = p_review);
    members text[];
    sample integer;
    batch_id text := new_id('ab');
    member record;
    excluded text[];
BEGIN
    IF review.type IS DISTINCT FROM 'review' OR review.state <> 'done'
       OR EXISTS (SELECT 1 FROM audit_batches WHERE review_task = p_review) THEN
        RETURN NULL;
    END IF;
    -- Settled when nothing it decided is still being checked (an edit waiting for its tool check, for one).
    IF EXISTS (SELECT 1 FROM items i JOIN revisions r ON r.id = i.current_revision
               WHERE i.state = 'checking'
                 AND (r.created_by_task = p_review OR review.input -> 'revisions' ? r.id)) THEN
        RETURN NULL;
    END IF;
    SELECT array_agg(i.current_revision ORDER BY random()) INTO members
    FROM items i JOIN revisions r ON r.id = i.current_revision
    WHERE i.state = 'accepted'
      AND (r.created_by_task = p_review OR EXISTS (
            SELECT 1 FROM checks k WHERE k.revision_id = r.id AND k.task_id = p_review AND k.kind = 'review'
              AND k.verdict = 'pass'));
    IF members IS NULL THEN
        RETURN NULL;
    END IF;
    sample := greatest(1, ceil(cardinality(members) * setting('audit.sample_rate')::text::numeric))::integer;
    INSERT INTO audit_batches (id, type, city_id, size, sample_size, threshold, created_by, review_task)
    VALUES (batch_id, NULL, review.city_id, cardinality(members), sample, 0, p_run, p_review);
    FOR member IN SELECT m.id, m.n FROM unnest(members) WITH ORDINALITY AS m(id, n) LOOP
        INSERT INTO audit_members (batch_id, revision_id, sampled) VALUES (batch_id, member.id, member.n <= sample);
        IF member.n <= sample THEN
            SELECT array_agg(DISTINCT x) INTO excluded FROM unnest(
                ARRAY[(SELECT created_by_run FROM revisions WHERE id = member.id), review.done_by]) AS x
            WHERE x IS NOT NULL;
            PERFORM enqueue(p_run, 'audit', 'audit:' || batch_id || ':' || member.id,
                            jsonb_build_object('batch', batch_id), review.city_id,
                            (SELECT i.place_id FROM items i JOIN revisions r ON r.item_id = i.id WHERE r.id = member.id),
                            (SELECT item_id FROM revisions WHERE id = member.id), member.id, excluded, NULL, 5);
        END IF;
    END LOOP;
    RETURN batch_id;
END;
$$;

-- The one revision a rejected item gets, or its retirement.
CREATE FUNCTION send_back(p_run text, p_task text, p_revision text, p_problems jsonb, p_revisable boolean,
                          p_exclude text[]) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    item items := (SELECT i FROM items i JOIN revisions r ON r.item_id = i.id WHERE r.id = p_revision);
    reason text := (SELECT string_agg(value, '; ') FROM jsonb_array_elements_text(p_problems));
    revised boolean := EXISTS (SELECT 1 FROM revisions r JOIN tasks t ON t.id = r.created_by_task
                               WHERE r.item_id = item.id AND t.type = 'revise' AND t.input ? 'from_review');
BEGIN
    IF NOT p_revisable OR revised THEN
        PERFORM retire(p_run, item.id, 'rejected: ' || reason);
        RETURN 'retired';
    END IF;
    IF item.state <> 'draft' THEN
        PERFORM transition(item.id, 'draft', p_run, p_task, 'sent back: ' || reason);
    END IF;
    PERFORM enqueue(p_run, 'revise', 'revise:' || p_revision,
                    jsonb_build_object('problems', p_problems, 'from_review', true), item.city_id, item.place_id,
                    item.id, p_revision, p_exclude, NULL, 8);
    RETURN 'revise';
END;
$$;

CREATE OR REPLACE FUNCTION advance(p_run text, p_revision text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    revision revisions;
    item items;
    result jsonb;
    round text;
    writer text[];
    review text;
BEGIN
    SELECT * INTO revision FROM revisions WHERE id = p_revision;
    SELECT * INTO item FROM items WHERE id = revision.item_id FOR UPDATE;
    IF item.current_revision IS DISTINCT FROM p_revision OR item.state <> 'checking' THEN
        RETURN jsonb_build_object('outcome', 'none');
    END IF;
    round := p_revision || ':' || floor(extract(epoch FROM item.checking_since) * 1000)::bigint;
    writer := ARRAY[revision.created_by_run];
    result := evaluate(p_revision);
    CASE result ->> 'outcome'
    WHEN 'wait' THEN
        IF result ->> 'missing' = 'tool' THEN
            PERFORM enqueue(p_run, 'tool_check', 'tool_check:' || round, '{}', item.city_id, item.place_id, item.id,
                            p_revision);
        ELSIF result ->> 'missing' = 'check' THEN
            PERFORM enqueue(p_run, CASE WHEN item.type = 'photo' THEN 'check_photo' ELSE 'check_translation' END,
                            'check:' || round, '{}', item.city_id, item.place_id, item.id, p_revision, writer,
                            p_revision);
        ELSE
            PERFORM ensure_review(p_run, p_revision);
        END IF;
    WHEN 'accept' THEN
        PERFORM settle(p_run, NULL, p_revision);
        SELECT k.task_id INTO review FROM checks k
        WHERE k.revision_id = p_revision AND k.kind = 'review' ORDER BY k.id DESC LIMIT 1;
        PERFORM plan_review_audit(p_run, coalesce(review, revision.created_by_task));
    WHEN 'revise' THEN
        PERFORM settle(p_run, NULL, p_revision);
        PERFORM enqueue(p_run, 'revise', 'revise:' || round, jsonb_build_object('problems', result -> 'problems'),
                        item.city_id, item.place_id, item.id, p_revision, '{}', NULL, 5);
    WHEN 'reject' THEN
        SELECT k.task_id INTO review FROM checks k
        WHERE k.revision_id = p_revision AND k.kind = 'review' ORDER BY k.id DESC LIMIT 1;
        PERFORM send_back(p_run, NULL, p_revision, result -> 'problems', (result ->> 'revisable')::boolean,
                          writer || coalesce((SELECT ARRAY[done_by] FROM tasks WHERE id = review), '{}'));
        IF review IS NOT NULL THEN
            PERFORM plan_review_audit(p_run, review);
        END IF;
    ELSE
        NULL;
    END CASE;
    RETURN result;
END;
$$;

-- A failed audit sends the erroneous items to their one revision and the rest of the batch back to review.
CREATE OR REPLACE FUNCTION settle_audit(p_run text, p_batch text) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    batch audit_batches;
    member record;
    found_errors integer;
    back text[] := '{}';
    reviewers text[];
BEGIN
    SELECT * INTO batch FROM audit_batches WHERE id = p_batch FOR UPDATE;
    IF batch.outcome <> 'open' OR EXISTS (
        SELECT 1 FROM tasks WHERE type = 'audit' AND input ->> 'batch' = p_batch AND state <> 'done') THEN
        RETURN batch.outcome;
    END IF;
    UPDATE audit_members m SET error = EXISTS (
        SELECT 1 FROM checks k WHERE k.revision_id = m.revision_id AND k.kind = 'audit'
          AND k.created_at >= batch.created_at AND k.verdict NOT IN ('supported', 'pass'))
    WHERE m.batch_id = p_batch AND m.sampled;
    SELECT count(*) INTO found_errors FROM audit_members WHERE batch_id = p_batch AND error;
    UPDATE audit_batches
    SET errors = found_errors, rate = found_errors::numeric / sample_size, settled_at = now(),
        outcome = CASE WHEN found_errors::numeric / sample_size <= threshold THEN 'passed' ELSE 'failed' END
    WHERE id = p_batch RETURNING * INTO batch;
    IF batch.outcome = 'failed' THEN
        reviewers := ARRAY(SELECT done_by FROM tasks WHERE id = batch.review_task AND done_by IS NOT NULL);
        FOR member IN
            SELECT m.revision_id, m.error, i.id AS item_id, r.created_by_run
            FROM audit_members m JOIN revisions r ON r.id = m.revision_id JOIN items i ON i.id = r.item_id
            WHERE m.batch_id = p_batch AND i.state = 'accepted' AND i.current_revision = m.revision_id
        LOOP
            IF member.error THEN
                PERFORM send_back(p_run, NULL, member.revision_id,
                                  (SELECT jsonb_agg(note) FROM checks WHERE revision_id = member.revision_id
                                     AND kind = 'audit' AND verdict NOT IN ('supported', 'pass')),
                                  true, ARRAY[member.created_by_run] || reviewers);
            ELSE
                PERFORM transition(member.item_id, 'checking', p_run, NULL, 'its audit batch failed; reviewed again');
                back := back || member.revision_id;
            END IF;
        END LOOP;
        IF cardinality(back) > 0 THEN
            PERFORM enqueue(p_run, 'review', 'review:audit:' || p_batch, jsonb_build_object('revisions', to_jsonb(back)),
                            batch.city_id, NULL, NULL, NULL,
                            ARRAY(SELECT DISTINCT created_by_run FROM revisions WHERE id = ANY(back)) || reviewers,
                            NULL, 10);
            PERFORM advance(p_run, r) FROM unnest(back) AS r;  -- their tool checks run again first
        END IF;
    END IF;
    RETURN batch.outcome;
END;
$$;

-- The system worker's periodic sweep: audits for review batches that settled without one, and for accepted
-- translations and photos (which have their own checks instead of a review), batched by type and city.
CREATE OR REPLACE FUNCTION plan_audits(p_token text, p_force boolean DEFAULT false) RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['system', 'editor']);
    review record;
    grp record;
    member record;
    batch_id text;
    sample integer;
    planned integer := 0;
BEGIN
    FOR review IN
        SELECT t.id FROM tasks t WHERE t.type = 'review' AND t.state = 'done'
          AND NOT EXISTS (SELECT 1 FROM audit_batches b WHERE b.review_task = t.id)
    LOOP
        IF plan_review_audit(run.id, review.id) IS NOT NULL THEN
            planned := planned + 1;
        END IF;
    END LOOP;
    FOR grp IN
        SELECT i.type, i.city_id, array_agg(i.current_revision ORDER BY random()) AS members
        FROM items i
        WHERE i.type IN ('translation', 'photo') AND i.state = 'accepted'
          AND NOT EXISTS (SELECT 1 FROM audit_members m WHERE m.revision_id = i.current_revision)
        GROUP BY i.type, i.city_id
        HAVING count(*) >= 10 OR p_force
    LOOP
        batch_id := new_id('ab');
        sample := greatest(1, ceil(cardinality(grp.members) * setting('audit.sample_rate')::text::numeric))::integer;
        INSERT INTO audit_batches (id, type, city_id, size, sample_size, threshold, created_by)
        VALUES (batch_id, grp.type, grp.city_id, cardinality(grp.members), sample, 0, run.id);
        FOR member IN SELECT m.id, m.n FROM unnest(grp.members) WITH ORDINALITY AS m(id, n) LOOP
            INSERT INTO audit_members (batch_id, revision_id, sampled) VALUES (batch_id, member.id, member.n <= sample);
            IF member.n <= sample THEN
                PERFORM enqueue(run.id, 'audit', 'audit:' || batch_id || ':' || member.id,
                                jsonb_build_object('batch', batch_id), grp.city_id,
                                (SELECT i.place_id FROM items i JOIN revisions r ON r.item_id = i.id WHERE r.id = member.id),
                                (SELECT item_id FROM revisions WHERE id = member.id), member.id,
                                ARRAY[(SELECT created_by_run FROM revisions WHERE id = member.id)], NULL, 5);
            END IF;
        END LOOP;
        planned := planned + 1;
    END LOOP;
    RETURN planned;
END;
$$;

-- Submitting a review decides each item of its batch. An edit is the reviewer's own revision: it passes the tool
-- checks and is then accepted without a second review.
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
            p_result ->> 'rulebook', coalesce(nullif(p_result ->> 'reason', ''), task.type));
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
            PERFORM record_check(run.id, task.id, decision ->> 'revision', NULL, 'review',
                                 CASE WHEN decision ->> 'decision' = 'reject' THEN 'fail' ELSE 'pass' END,
                                 decision ->> 'note',
                                 jsonb_build_object('decision', decision ->> 'decision',
                                                    'revisable', coalesce((decision ->> 'revisable')::boolean, false)));
            IF decision ->> 'decision' = 'edit' THEN
                PERFORM transition(item.id, 'draft', run.id, task.id, 'edited in review');
                new_revision := create_revision(run.id, task.id, item.id, item.type, item.place_id, item.city_id,
                                                NULL, NULL, 'en', decision -> 'body', coalesce(decision -> 'claims', '[]'),
                                                p_result ->> 'rulebook', 'edited in review: ' || (decision ->> 'note'));
                next := next || jsonb_build_object(decision ->> 'revision', advance(run.id, new_revision));
            ELSE
                next := next || jsonb_build_object(decision ->> 'revision', advance(run.id, decision ->> 'revision'));
            END IF;
        END LOOP;
        PERFORM plan_review_audit(run.id, task.id);
        outcome := jsonb_build_object('decided', next);
    ELSE
        outcome := outcome || jsonb_build_object('next', advance(run.id, coalesce(new_revision, task.revision_id)));
    END IF;
    RETURN outcome;
END;
$$;

-- Research writes everything for the cell: places, their stories, and a guide for each new place.
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
        IF entry ? 'guide' THEN
            IF EXISTS (SELECT 1 FROM items i WHERE i.place_id = places_by_index[cardinality(places_by_index)]
                       AND i.type = 'guide' AND i.state <> 'retired') THEN
                RAISE EXCEPTION 'place % already has guide information', place_id USING ERRCODE = '22023';
            END IF;
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
                              'stories', stories, 'guides', guides, 'leads_open', remaining);
END;
$$;

CREATE FUNCTION record_run_tokens(p_run text, p_tokens bigint) RETURNS void
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
    UPDATE runs SET tokens = p_tokens WHERE id = p_run AND ended_at IS NOT NULL AND kind = 'worker'
$$;

GRANT EXECUTE ON FUNCTION record_run_tokens(text, bigint) TO psst_platform_worker;
SELECT apply_read_grants();

-- Work in flight under the old loop: its narrow checks and single-item tasks are cancelled, open audit batches are
-- superseded, and every unpublished story and guide still in progress is reviewed in batches of up to ten per city.
DO $$
DECLARE
    migration text := new_id('ru');
    group_revisions text[];
    entry record;
BEGIN
    INSERT INTO runs (id, kind, operator, token_hash, notes, ended_at)
    VALUES (migration, 'system', 'schema migration', gen_random_bytes(32), 'migration 0026: content loop', now());
    UPDATE tasks SET state = 'cancelled', leased_by = NULL, leased_until = NULL,
                     problem = 'replaced by the research and review loop (decision 22)'
    WHERE state IN ('queued', 'leased', 'failed')
      AND type IN ('write_story', 'write_guide', 'check_claims_a', 'check_claims_b', 'check_item', 'escalate',
                   'revise', 'audit');
    UPDATE audit_batches SET outcome = 'superseded', settled_at = now() WHERE outcome = 'open';
    FOR entry IN
        SELECT i.id, i.state FROM items i
        WHERE i.type IN ('story', 'guide') AND i.state IN ('draft', 'checking', 'accepted')
          AND NOT EXISTS (SELECT 1 FROM audit_members m JOIN audit_batches b ON b.id = m.batch_id
                          WHERE m.revision_id = i.current_revision
                            AND (b.outcome = 'passed' OR (b.outcome = 'failed' AND m.sampled AND NOT m.error)))
    LOOP
        IF entry.state <> 'checking' THEN
            PERFORM transition(entry.id, 'checking', migration, NULL, 'reviewed under the new content loop');
        END IF;
    END LOOP;
    FOR entry IN
        SELECT i.city_id, array_agg(i.current_revision ORDER BY p.h3_r7, i.place_id, i.type) AS revisions
        FROM items i JOIN places p ON p.id = i.place_id
        WHERE i.type IN ('story', 'guide') AND i.state = 'checking'
        GROUP BY i.city_id
    LOOP
        FOR n IN 0 .. (cardinality(entry.revisions) - 1) / 10 LOOP
            group_revisions := entry.revisions[n * 10 + 1 : n * 10 + 10];
            PERFORM enqueue(migration, 'review', 'review:migration:' || entry.city_id || ':' || n,
                            jsonb_build_object('revisions', to_jsonb(group_revisions)), entry.city_id, NULL, NULL, NULL,
                            ARRAY(SELECT DISTINCT created_by_run FROM revisions WHERE id = ANY(group_revisions)),
                            NULL, 10);
            PERFORM advance(migration, r) FROM unnest(group_revisions) AS r;
        END LOOP;
    END LOOP;
END;
$$;
