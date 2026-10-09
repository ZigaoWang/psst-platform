-- Tasks and audits (design.md, sections 7.3 to 7.7 and 8). Every job is a task with a lease. Submitting a result
-- applies it through the lifecycle functions and then `advance`, which makes sure the revision's next task
-- exists: a tool check, the two claim checks and the item check, an escalation, or a revision.
SET search_path = psst, public;

CREATE TABLE task_types (
    name        text PRIMARY KEY CHECK (name ~ '^[a-z_]+$'),
    runner      text NOT NULL CHECK (runner IN ('worker', 'system')),
    description text NOT NULL
);
INSERT INTO task_types (name, runner, description) VALUES
    ('research_cell', 'worker', 'Find the places in a research cell worth a story, and account for every lead.'),
    ('write_story', 'worker', 'Write one story about a place, with claims and evidence.'),
    ('write_guide', 'worker', 'Write a place''s guide information, with claims and evidence.'),
    ('write_trail', 'worker', 'Write a trail linking places with published stories.'),
    ('revise', 'worker', 'Write a new revision that fixes the problems the checks found.'),
    ('translate', 'worker', 'Translate an accepted revision into Simplified Chinese.'),
    ('check_claims_a', 'worker', 'Check each claim against its passages: does the passage say this?'),
    ('check_claims_b', 'worker', 'Read what each passage says about the claim''s subject, then compare.'),
    ('check_item', 'worker', 'Check the whole text against its claims and the content standard.'),
    ('check_photo', 'worker', 'Look at a photo and check it shows the place, with an accurate description.'),
    ('check_translation', 'worker', 'Translate back without the English and compare claim by claim.'),
    ('escalate', 'worker', 'Decide disputed claims or items from the full snapshots.'),
    ('audit', 'worker', 'Recheck a sampled accepted revision from the full snapshots.'),
    ('find_photos', 'worker', 'Find freely licensed photos of a place.'),
    ('tool_check', 'system', 'Run the tool checks on a revision.'),
    ('resolve_places', 'system', 'Look up coordinates and areas for new places.');

INSERT INTO settings (key, value, note) VALUES
    ('routing.research_cell', '"claude-sonnet-5-5"', 'Model that researches cells.'),
    ('routing.write_story', '"claude-sonnet-5-5"', 'Model that writes stories.'),
    ('routing.write_guide', '"claude-haiku-5-5"', 'Model that writes guide information.'),
    ('routing.write_trail', '"claude-sonnet-5-5"', 'Model that writes trails.'),
    ('routing.revise', '"claude-sonnet-5-5"', 'Model that revises what the checks sent back.'),
    ('routing.translate', '"claude-sonnet-5-5"', 'Model that translates.'),
    ('routing.check_claims_a', '"claude-haiku-5-5"', 'Model for the first claim check.'),
    ('routing.check_claims_b', '"claude-haiku-5-5"', 'Model for the second claim check.'),
    ('routing.check_item', '"claude-haiku-5-5"', 'Model for the whole-item check.'),
    ('routing.check_photo', '"claude-haiku-5-5"', 'Model that checks photos.'),
    ('routing.check_translation', '"claude-haiku-5-5"', 'Model that checks translations.'),
    ('routing.escalate', '"claude-sonnet-5-5"', 'Model that decides escalations.'),
    ('routing.audit', '"claude-sonnet-5-5"', 'Model that audits accepted work.'),
    ('routing.find_photos', '"claude-haiku-5-5"', 'Model that finds photos.'),
    ('lease.default', '60', 'Minutes a lease lasts unless the task type has its own.'),
    ('lease.research_cell', '240', 'Minutes a research lease lasts.'),
    ('lease.write_story', '90', 'Minutes a story-writing lease lasts.'),
    ('lease.max_attempts', '3', 'Leases a task gets before it waits for an editor.');

CREATE TABLE tasks (
    id            text PRIMARY KEY CHECK (id ~ id_pattern('tk')),
    type          text NOT NULL REFERENCES task_types,
    state         text NOT NULL DEFAULT 'queued' CHECK (state IN ('queued', 'leased', 'done', 'failed', 'cancelled')),
    -- What the task is for, unique, so the same job is never queued twice.
    purpose       text NOT NULL UNIQUE,
    priority      integer NOT NULL DEFAULT 0,
    model         text,
    city_id       bigint REFERENCES cities,
    place_id      text REFERENCES places,
    item_id       text REFERENCES items,
    revision_id   text REFERENCES revisions,
    input         jsonb NOT NULL DEFAULT '{}',
    -- Runs that may not take the task, and a key no run may hold two tasks of (the revision, for checks).
    exclude_runs  text[] NOT NULL DEFAULT '{}',
    independence  text,
    leased_by     text REFERENCES runs,
    leased_until  timestamptz,
    attempts      integer NOT NULL DEFAULT 0,
    prompt        text,
    result        jsonb,
    problem       text,
    created_by    text NOT NULL REFERENCES runs,
    created_at    timestamptz NOT NULL DEFAULT now(),
    done_by       text REFERENCES runs,
    done_at       timestamptz,
    CHECK ((state = 'leased') = (leased_by IS NOT NULL AND leased_until IS NOT NULL)),
    CHECK ((state = 'done') = (done_at IS NOT NULL))
);
CREATE INDEX tasks_queue_idx ON tasks (type, model, priority DESC, created_at) WHERE state = 'queued';
CREATE INDEX tasks_leased_idx ON tasks (leased_until) WHERE state = 'leased';
CREATE INDEX tasks_revision_idx ON tasks (revision_id);
CREATE INDEX tasks_independence_idx ON tasks (independence) WHERE independence IS NOT NULL;
CREATE INDEX tasks_state_idx ON tasks (state, type);

-- Every lease ever given, so independence holds across expired and returned leases too.
CREATE TABLE task_leases (
    task_id   text NOT NULL REFERENCES tasks,
    run_id    text NOT NULL REFERENCES runs,
    leased_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (task_id, run_id, leased_at)
);
CREATE INDEX task_leases_run_idx ON task_leases (run_id);
CREATE TRIGGER task_leases_history BEFORE UPDATE OR DELETE ON task_leases FOR EACH ROW EXECUTE FUNCTION refuse_change();

ALTER TABLE revisions ADD FOREIGN KEY (created_by_task) REFERENCES tasks;
ALTER TABLE checks ADD FOREIGN KEY (task_id) REFERENCES tasks;
ALTER TABLE transitions ADD FOREIGN KEY (task_id) REFERENCES tasks;

-- Queues a task unless one with the same purpose exists. Returns the task's id either way.
CREATE FUNCTION enqueue(p_run text, p_type text, p_purpose text, p_input jsonb, p_city bigint, p_place text,
                        p_item text, p_revision text, p_exclude text[] DEFAULT '{}', p_independence text DEFAULT NULL,
                        p_priority integer DEFAULT 0) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    task_id text;
    runner text := (SELECT t.runner FROM task_types t WHERE t.name = p_type);
BEGIN
    IF runner IS NULL THEN
        RAISE EXCEPTION 'unknown task type %', p_type USING ERRCODE = '22023';
    END IF;
    INSERT INTO tasks (id, type, purpose, priority, model, city_id, place_id, item_id, revision_id, input,
                       exclude_runs, independence, created_by)
    VALUES (new_id('tk'), p_type, p_purpose, p_priority,
            CASE WHEN runner = 'worker' THEN setting('routing.' || p_type) #>> '{}' END,
            p_city, p_place, p_item, p_revision, coalesce(p_input, '{}'), coalesce(p_exclude, '{}'), p_independence,
            p_run)
    ON CONFLICT (purpose) DO NOTHING
    RETURNING id INTO task_id;
    RETURN coalesce(task_id, (SELECT id FROM tasks WHERE purpose = p_purpose));
END;
$$;

-- transition, now also cancelling the open check tasks of an item that leaves checking, so no worker spends
-- time on a revision that has been settled or sent back.
CREATE OR REPLACE FUNCTION transition(p_item text, p_to text, p_run text, p_task text, p_reason text) RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    item items;
BEGIN
    SELECT * INTO item FROM items WHERE id = p_item FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'unknown item %', p_item USING ERRCODE = 'P0002';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM lifecycle_moves WHERE from_state = item.state AND to_state = p_to) THEN
        RAISE EXCEPTION 'item % can''t move from % to %', p_item, item.state, p_to USING ERRCODE = 'P0001';
    END IF;
    PERFORM set_config('psst.in_transition', 'on', true);
    UPDATE items SET state = p_to,
                     checking_since = CASE WHEN p_to = 'checking' THEN now() ELSE checking_since END
    WHERE id = p_item;
    PERFORM set_config('psst.in_transition', 'off', true);
    INSERT INTO transitions (item_id, from_state, to_state, revision_id, run_id, task_id, reason)
    VALUES (p_item, item.state, p_to, item.current_revision, p_run, p_task, p_reason);
    IF item.state = 'checking' THEN
        UPDATE tasks SET state = 'cancelled', leased_by = NULL, leased_until = NULL,
                         problem = 'the revision is no longer being checked'
        WHERE item_id = p_item AND state IN ('queued', 'leased') AND (id IS DISTINCT FROM p_task)
          AND type IN ('tool_check', 'check_claims_a', 'check_claims_b', 'check_item', 'check_photo',
                       'check_translation', 'escalate');
    END IF;
END;
$$;

-- Makes sure the next step for a revision under check exists, or settles it. Safe to call any time.
CREATE FUNCTION advance(p_run text, p_revision text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    revision revisions;
    item items;
    result jsonb;
    round text;
    writer text[];
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
        ELSIF item.type = 'translation' THEN
            PERFORM enqueue(p_run, 'check_translation', 'check_translation:' || round, '{}', item.city_id,
                            item.place_id, item.id, p_revision, writer, p_revision);
        ELSE
            IF EXISTS (SELECT 1 FROM claims WHERE revision_id = p_revision) THEN
                PERFORM enqueue(p_run, t, t || ':' || round, '{}', item.city_id, item.place_id, item.id, p_revision,
                                writer, p_revision)
                FROM unnest(ARRAY['check_claims_a', 'check_claims_b']) AS t;
            END IF;
            PERFORM enqueue(p_run, CASE WHEN item.type = 'photo' THEN 'check_photo' ELSE 'check_item' END,
                            'check_item:' || round, '{}', item.city_id, item.place_id, item.id, p_revision, writer,
                            p_revision);
        END IF;
    WHEN 'escalate' THEN
        PERFORM enqueue(p_run, 'escalate', 'escalate:' || round,
                        jsonb_build_object('claims', result -> 'claims', 'item', result -> 'item'),
                        item.city_id, item.place_id, item.id, p_revision, writer, p_revision, 10);
    WHEN 'accept', 'revise' THEN
        PERFORM settle(p_run, NULL, p_revision);
        IF result ->> 'outcome' = 'revise' THEN
            PERFORM enqueue(p_run, 'revise', 'revise:' || round, jsonb_build_object('problems', result -> 'problems'),
                            item.city_id, item.place_id, item.id, p_revision, '{}', NULL, 5);
        END IF;
    ELSE
        NULL;
    END CASE;
    RETURN result;
END;
$$;

-- Leasing ----------------------------------------------------------------------------------------------------

CREATE FUNCTION lease_minutes(p_type text) RETURNS integer
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = psst, pg_temp AS $$
    SELECT coalesce((SELECT value FROM settings WHERE key = 'lease.' || p_type),
                    (SELECT value FROM settings WHERE key = 'lease.default'))::text::integer
$$;

-- Returns expired leases to the queue (or to an editor, after the last attempt).
CREATE FUNCTION expire_leases() RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    expired integer;
BEGIN
    UPDATE tasks
    SET state = CASE WHEN attempts >= setting('lease.max_attempts')::text::integer THEN 'failed' ELSE 'queued' END,
        leased_by = NULL, leased_until = NULL, problem = 'the lease expired'
    WHERE state = 'leased' AND leased_until < now();
    GET DIAGNOSTICS expired = ROW_COUNT;
    RETURN expired;
END;
$$;

-- Leases the next task of the given types this run may take: routed to its model, not excluded, and not sharing
-- an independence key with any task the run ever held. Returns no row when there is none.
CREATE FUNCTION lease_task(p_token text, p_types text[], p_city bigint DEFAULT NULL) RETURNS SETOF tasks
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['worker', 'system']);
    task tasks;
BEGIN
    PERFORM expire_leases();
    SELECT t.* INTO task FROM tasks t JOIN task_types y ON y.name = t.type
    WHERE t.state = 'queued' AND t.type = ANY(p_types)
      AND (p_city IS NULL OR t.city_id = p_city)
      AND y.runner = run.kind
      AND (run.kind = 'system' OR t.model = run.model)
      AND NOT run.id = ANY(t.exclude_runs)
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

-- The task a run holds, locked, or an error.
CREATE FUNCTION held_task(p_run runs, p_task text) RETURNS tasks
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    task tasks;
BEGIN
    SELECT * INTO task FROM tasks WHERE id = p_task FOR UPDATE;
    IF NOT FOUND OR task.state <> 'leased' OR task.leased_by <> p_run.id THEN
        RAISE EXCEPTION 'task % isn''t leased to this run', p_task USING ERRCODE = '42501';
    END IF;
    IF task.leased_until < now() THEN
        RAISE EXCEPTION 'the lease on task % has expired', p_task USING ERRCODE = '42501';
    END IF;
    RETURN task;
END;
$$;

-- Gives a task back: queued again, or failed after the last attempt.
CREATE FUNCTION return_task(p_token text, p_task text, p_problem text) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['worker', 'system']);
    task tasks := held_task(run, p_task);
    next_state text := CASE WHEN task.attempts >= setting('lease.max_attempts')::text::integer THEN 'failed'
                            ELSE 'queued' END;
BEGIN
    UPDATE tasks SET state = next_state, leased_by = NULL, leased_until = NULL, problem = p_problem WHERE id = task.id;
    RETURN next_state;
END;
$$;

-- Submitting ---------------------------------------------------------------------------------------------------

-- The verdict a result gives for each id in `p_ids`, or an error naming the first one missing.
CREATE FUNCTION verdicts_for(p_result jsonb, p_ids text[]) RETURNS TABLE (id text, verdict text, note text)
LANGUAGE plpgsql IMMUTABLE SET search_path = psst, pg_temp AS $$
DECLARE
    wanted text;
    entry jsonb;
BEGIN
    FOREACH wanted IN ARRAY p_ids LOOP
        SELECT value INTO entry FROM jsonb_array_elements(coalesce(p_result -> 'verdicts', '[]'))
        WHERE value ->> 'claim' = wanted LIMIT 1;
        IF entry IS NULL THEN
            RAISE EXCEPTION 'the result has no verdict for claim %', wanted USING ERRCODE = '22023';
        END IF;
        id := wanted;
        verdict := entry ->> 'verdict';
        note := entry ->> 'note';
        RETURN NEXT;
    END LOOP;
END;
$$;

CREATE FUNCTION submit_task(p_token text, p_task text, p_result jsonb, p_prompt text DEFAULT NULL) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['worker', 'system']);
    task tasks := held_task(run, p_task);
    item items;
    claim_ids text[];
    entry record;
    new_revision text;
    outcome jsonb := '{}';
    check_kind text;
BEGIN
    SELECT * INTO item FROM items WHERE id = task.item_id;
    CASE task.type
    WHEN 'check_claims_a', 'check_claims_b', 'escalate', 'audit' THEN
        check_kind := CASE task.type WHEN 'check_claims_a' THEN 'claim_a' WHEN 'check_claims_b' THEN 'claim_b'
                                     WHEN 'escalate' THEN 'escalation' ELSE 'audit' END;
        claim_ids := CASE WHEN task.type = 'escalate' THEN ARRAY(SELECT jsonb_array_elements_text(task.input -> 'claims'))
                          ELSE ARRAY(SELECT id FROM claims WHERE revision_id = task.revision_id ORDER BY n) END;
        FOR entry IN SELECT * FROM verdicts_for(p_result, claim_ids) LOOP
            PERFORM record_check(run.id, task.id, task.revision_id, entry.id, check_kind, entry.verdict, entry.note);
        END LOOP;
        IF task.type = 'audit' OR (task.type = 'escalate' AND (task.input ->> 'item')::boolean) THEN
            PERFORM record_check(run.id, task.id, task.revision_id, NULL, check_kind, p_result #>> '{item,verdict}',
                                 p_result #>> '{item,note}', coalesce(p_result -> 'item', '{}'));
        END IF;
    WHEN 'check_item', 'check_photo', 'check_translation' THEN
        IF p_result ->> 'verdict' = 'pass' AND jsonb_array_length(coalesce(p_result -> 'untraced', '[]')) > 0 THEN
            RAISE EXCEPTION 'details no claim states fail the item check' USING ERRCODE = '22023';
        END IF;
        PERFORM record_check(run.id, task.id, task.revision_id, NULL,
                             CASE WHEN task.type = 'check_translation' THEN 'translation' ELSE 'item' END,
                             p_result ->> 'verdict', p_result ->> 'note', p_result);
    WHEN 'write_story', 'write_guide', 'write_trail', 'revise', 'translate' THEN
        new_revision := create_revision(
            run.id, task.id,
            CASE WHEN task.type = 'revise' THEN task.item_id
                 WHEN task.type = 'write_guide' THEN (SELECT id FROM items WHERE place_id = task.place_id
                                                       AND type = 'guide' AND state <> 'retired' LIMIT 1)
                 WHEN task.type = 'translate' THEN (SELECT id FROM items WHERE translates = task.item_id
                                                     AND language = p_result ->> 'language' AND state <> 'retired')
            END,
            CASE task.type WHEN 'write_story' THEN 'story' WHEN 'write_guide' THEN 'guide' WHEN 'write_trail' THEN 'trail'
                           WHEN 'translate' THEN 'translation' ELSE item.type END,
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
    ELSE
        outcome := outcome || jsonb_build_object('next', advance(run.id, coalesce(new_revision, task.revision_id)));
    END IF;
    RETURN outcome;
END;
$$;

-- Audits -------------------------------------------------------------------------------------------------------

CREATE TABLE audit_batches (
    id          text PRIMARY KEY CHECK (id ~ id_pattern('ab')),
    type        text NOT NULL REFERENCES item_types,
    city_id     bigint NOT NULL REFERENCES cities,
    size        integer NOT NULL CHECK (size > 0),
    sample_size integer NOT NULL CHECK (sample_size > 0),
    errors      integer,
    rate        numeric,
    threshold   numeric NOT NULL,
    outcome     text NOT NULL DEFAULT 'open' CHECK (outcome IN ('open', 'passed', 'failed')),
    created_by  text NOT NULL REFERENCES runs,
    created_at  timestamptz NOT NULL DEFAULT now(),
    settled_at  timestamptz,
    CHECK ((outcome = 'open') = (settled_at IS NULL))
);
CREATE INDEX audit_batches_open_idx ON audit_batches (created_at) WHERE outcome = 'open';

CREATE TABLE audit_members (
    batch_id    text NOT NULL REFERENCES audit_batches,
    revision_id text NOT NULL REFERENCES revisions,
    sampled     boolean NOT NULL,
    error       boolean,
    PRIMARY KEY (batch_id, revision_id)
);
CREATE INDEX audit_members_revision_idx ON audit_members (revision_id);

-- Groups accepted revisions not yet in an open or passed batch into batches by type and city, samples each, and
-- queues an audit task per sampled revision. A group waits for `audit.min_batch` revisions unless `p_force`.
CREATE FUNCTION plan_audits(p_token text, p_force boolean DEFAULT false) RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['system', 'editor']);
    min_batch integer := setting('audit.min_batch')::text::integer;
    min_sample integer := setting('audit.min_sample')::text::integer;
    extra numeric := setting('audit.extra_sample_rate')::text::numeric;
    grp record;
    new_batch text;
    sample integer;
    created integer := 0;
BEGIN
    FOR grp IN
        SELECT i.type, i.city_id, array_agg(i.current_revision ORDER BY i.current_revision) AS revisions
        FROM items i
        WHERE i.state = 'accepted' AND NOT EXISTS (
            SELECT 1 FROM audit_members m JOIN audit_batches b ON b.id = m.batch_id
            WHERE m.revision_id = i.current_revision AND b.outcome IN ('open', 'passed'))
        GROUP BY i.type, i.city_id
    LOOP
        CONTINUE WHEN cardinality(grp.revisions) < min_batch AND NOT p_force;
        sample := least(cardinality(grp.revisions),
                        min_sample + ceil(extra * greatest(cardinality(grp.revisions) - min_sample, 0))::integer);
        new_batch := new_id('ab');
        INSERT INTO audit_batches (id, type, city_id, size, sample_size, threshold, created_by)
        VALUES (new_batch, grp.type, grp.city_id, cardinality(grp.revisions), sample,
                setting('audit.threshold.' || grp.type)::text::numeric, run.id);
        INSERT INTO audit_members (batch_id, revision_id, sampled)
        SELECT new_batch, r, row_number() OVER (ORDER BY random()) <= sample FROM unnest(grp.revisions) AS r;
        PERFORM enqueue(run.id, 'audit', 'audit:' || new_batch || ':' || m.revision_id,
                        jsonb_build_object('batch', new_batch), i.city_id, i.place_id, i.id, m.revision_id,
                        ARRAY[r.created_by_run], m.revision_id)
        FROM audit_members m JOIN revisions r ON r.id = m.revision_id JOIN items i ON i.id = r.item_id
        WHERE m.batch_id = new_batch AND m.sampled;
        created := created + 1;
    END LOOP;
    RETURN created;
END;
$$;

-- Settles a batch once every audit task in it is done: measures the error rate, and if it is above the
-- threshold sends the erroneous revisions back to their writers and everything else in the batch back to
-- checking. Returns the batch's outcome.
CREATE FUNCTION settle_audit(p_run text, p_batch text) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    batch audit_batches;
    member record;
    found_errors integer;
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
        FOR member IN
            SELECT m.revision_id, m.error, i.id AS item_id, i.city_id, i.place_id, i.current_revision
            FROM audit_members m JOIN revisions r ON r.id = m.revision_id JOIN items i ON i.id = r.item_id
            WHERE m.batch_id = p_batch AND i.state = 'accepted' AND i.current_revision = m.revision_id
        LOOP
            IF member.error THEN
                PERFORM transition(member.item_id, 'draft', p_run, NULL, 'the audit found an error');
                PERFORM enqueue(p_run, 'revise', 'revise:audit:' || p_batch || ':' || member.revision_id,
                                jsonb_build_object('problems', (
                                    SELECT jsonb_agg(note) FROM checks WHERE revision_id = member.revision_id
                                      AND kind = 'audit' AND verdict NOT IN ('supported', 'pass'))),
                                member.city_id, member.place_id, member.item_id, member.revision_id, '{}', NULL, 5);
            ELSE
                PERFORM transition(member.item_id, 'checking', p_run, NULL,
                                   'its audit batch failed, so it is checked again');
                PERFORM advance(p_run, member.revision_id);
            END IF;
        END LOOP;
    END IF;
    RETURN batch.outcome;
END;
$$;

GRANT EXECUTE ON FUNCTION lease_task(text, text[], bigint), submit_task(text, text, jsonb, text),
    return_task(text, text, text) TO psst_platform_worker, psst_platform_system;
GRANT EXECUTE ON FUNCTION plan_audits(text, boolean) TO psst_platform_system, psst_platform_console;
SELECT apply_read_grants();
