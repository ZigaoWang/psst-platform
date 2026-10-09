-- The admin console (design.md, section 12): editor accounts, sessions, logged actions, and the editor actions
-- themselves. Passwords are checked inside the database, so no password hash ever leaves it. Each session acts
-- under its own editor run.
SET search_path = psst, public;

CREATE TABLE console_accounts (
    id            text PRIMARY KEY CHECK (id ~ id_pattern('ac')),
    name          text NOT NULL UNIQUE CHECK (name ~ '^[a-z][a-z0-9_.-]{1,39}$'),
    password_hash text NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    disabled_at   timestamptz
);

CREATE TABLE console_sessions (
    token_hash bytea PRIMARY KEY,
    account_id text NOT NULL REFERENCES console_accounts,
    run_id     text NOT NULL REFERENCES runs,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    ended_at   timestamptz
);
CREATE INDEX console_sessions_account_idx ON console_sessions (account_id);

CREATE TABLE console_actions (
    id         bigserial PRIMARY KEY,
    account_id text NOT NULL REFERENCES console_accounts,
    run_id     text NOT NULL REFERENCES runs,
    action     text NOT NULL,
    target     text,
    detail     jsonb NOT NULL DEFAULT '{}',
    at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX console_actions_at_idx ON console_actions (at DESC);
CREATE TRIGGER console_actions_history BEFORE UPDATE OR DELETE ON console_actions
    FOR EACH ROW EXECUTE FUNCTION refuse_change();

INSERT INTO read_limits VALUES
    ('console_accounts', ARRAY['psst_platform_console']),
    ('console_sessions', ARRAY[]::text[]),
    ('console_actions', ARRAY['psst_platform_console']);

-- Accounts are added from the command line by the schema owner. Returns the account id.
CREATE FUNCTION console_add_account(p_name text, p_password text) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    account text := new_id('ac');
BEGIN
    IF char_length(p_password) < 16 THEN
        RAISE EXCEPTION 'a console password has at least 16 characters' USING ERRCODE = '22023';
    END IF;
    INSERT INTO console_accounts (id, name, password_hash) VALUES (account, p_name, crypt(p_password, gen_salt('bf', 12)));
    RETURN account;
END;
$$;

-- Signs in: checks the password and starts a session with its own editor run. Returns the session token, or
-- null for a wrong name or password (the same answer for both).
CREATE FUNCTION console_sign_in(p_name text, p_password text, p_hours integer DEFAULT 12) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    account console_accounts;
    token text := encode(gen_random_bytes(32), 'hex');
    run_id text := new_id('ru');
BEGIN
    SELECT * INTO account FROM console_accounts WHERE name = lower(p_name) AND disabled_at IS NULL;
    IF NOT FOUND OR account.password_hash <> crypt(p_password, account.password_hash) THEN
        PERFORM pg_sleep(0.2);
        RETURN NULL;
    END IF;
    INSERT INTO runs (id, kind, operator, token_hash, notes)
    VALUES (run_id, 'editor', account.name, digest(encode(gen_random_bytes(32), 'hex'), 'sha256'), 'console session');
    INSERT INTO console_sessions (token_hash, account_id, run_id, expires_at)
    VALUES (digest(token, 'sha256'), account.id, run_id, now() + make_interval(hours => least(p_hours, 24)));
    INSERT INTO console_actions (account_id, run_id, action) VALUES (account.id, run_id, 'sign in');
    RETURN token;
END;
$$;

-- The signed-in account for a session token, or no row.
CREATE FUNCTION console_session(p_token text)
RETURNS TABLE (account_id text, name text, run_id text, expires_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
    SELECT a.id, a.name, s.run_id, s.expires_at
    FROM console_sessions s JOIN console_accounts a ON a.id = s.account_id
    WHERE s.token_hash = digest(coalesce(p_token, ''), 'sha256') AND s.ended_at IS NULL AND s.expires_at > now()
      AND a.disabled_at IS NULL
$$;

CREATE FUNCTION console_sign_out(p_token text) RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    session record;
BEGIN
    SELECT * INTO session FROM console_session(p_token);
    IF FOUND THEN
        UPDATE console_sessions SET ended_at = now() WHERE token_hash = digest(p_token, 'sha256');
        UPDATE runs SET ended_at = now() WHERE id = session.run_id;
        INSERT INTO console_actions (account_id, run_id, action) VALUES (session.account_id, session.run_id, 'sign out');
    END IF;
END;
$$;

-- The session's editor run, after logging the action, or an error for a session that has ended.
CREATE FUNCTION console_act(p_token text, p_action text, p_target text, p_detail jsonb DEFAULT '{}') RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    session record;
BEGIN
    SELECT * INTO session FROM console_session(p_token);
    IF NOT FOUND THEN
        RAISE EXCEPTION 'sign in again' USING ERRCODE = '28000';
    END IF;
    INSERT INTO console_actions (account_id, run_id, action, target, detail)
    VALUES (session.account_id, session.run_id, p_action, p_target, coalesce(p_detail, '{}'));
    RETURN session.run_id;
END;
$$;

-- Editor actions ---------------------------------------------------------------------------------------------

CREATE FUNCTION console_retire(p_token text, p_item text, p_reason text) RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
BEGIN
    IF coalesce(btrim(p_reason), '') = '' THEN
        RAISE EXCEPTION 'say why it is retired' USING ERRCODE = '22023';
    END IF;
    PERFORM retire(console_act(p_token, 'retire', p_item, jsonb_build_object('reason', p_reason)), p_item, p_reason);
END;
$$;

-- Sends an accepted or published item back to checking (it stays live meanwhile) and queues fresh checks.
CREATE FUNCTION console_recheck(p_token text, p_item text, p_reason text) RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run text := console_act(p_token, 'recheck', p_item, jsonb_build_object('reason', p_reason));
BEGIN
    PERFORM transition(p_item, 'checking', run, NULL, coalesce(nullif(btrim(p_reason), ''), 'an editor asked'));
    PERFORM advance(run, (SELECT current_revision FROM items WHERE id = p_item));
END;
$$;

-- An editor's verdict on a claim (or, with no claim, on the whole item). It outranks every model verdict.
CREATE FUNCTION console_verdict(p_token text, p_revision text, p_claim text, p_verdict text, p_note text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run text := console_act(p_token, 'verdict', coalesce(p_claim, p_revision),
                            jsonb_build_object('verdict', p_verdict, 'note', p_note));
    item items := (SELECT i FROM items i JOIN revisions r ON r.item_id = i.id WHERE r.id = p_revision);
BEGIN
    PERFORM record_check(run, NULL, p_revision, p_claim, 'editor', p_verdict, p_note);
    IF item.state = 'checking' THEN
        RETURN advance(run, p_revision);
    ELSIF item.state IN ('accepted', 'published') AND p_verdict NOT IN ('supported', 'pass') THEN
        PERFORM transition(item.id, 'draft', run, NULL, 'an editor found an error: ' || p_note);
        PERFORM enqueue(run, 'revise', 'revise:editor:' || p_revision || ':' || coalesce(p_claim, 'item'),
                        jsonb_build_object('problems', jsonb_build_array(p_note)), item.city_id, item.place_id,
                        item.id, p_revision, '{}', NULL, 10);
    END IF;
    RETURN jsonb_build_object('outcome', 'recorded');
END;
$$;

CREATE FUNCTION console_task(p_token text, p_task text, p_action text) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    task tasks;
BEGIN
    PERFORM console_act(p_token, p_action || ' task', p_task);
    SELECT * INTO task FROM tasks WHERE id = p_task FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'unknown task %', p_task USING ERRCODE = 'P0002';
    END IF;
    IF p_action = 'release' AND task.state = 'leased' THEN
        UPDATE tasks SET state = 'queued', leased_by = NULL, leased_until = NULL, problem = 'released by an editor'
        WHERE id = p_task;
    ELSIF p_action = 'requeue' AND task.state IN ('failed', 'cancelled') THEN
        UPDATE tasks SET state = 'queued', attempts = 0, problem = NULL WHERE id = p_task;
    ELSIF p_action = 'cancel' AND task.state IN ('queued', 'leased', 'failed') THEN
        UPDATE tasks SET state = 'cancelled', leased_by = NULL, leased_until = NULL, problem = 'cancelled by an editor'
        WHERE id = p_task;
    ELSE
        RAISE EXCEPTION 'a % task can''t be %d', task.state, p_action USING ERRCODE = 'P0001';
    END IF;
    RETURN (SELECT state FROM tasks WHERE id = p_task);
END;
$$;

CREATE FUNCTION console_end_run(p_token text, p_run text) RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
BEGIN
    PERFORM console_act(p_token, 'end run', p_run);
    UPDATE runs SET ended_at = now(), notes = coalesce(notes || ' ', '') || '(ended from the console)'
    WHERE id = p_run AND ended_at IS NULL AND kind <> 'editor';
    UPDATE tasks SET state = 'queued', leased_by = NULL, leased_until = NULL, problem = 'its run was ended'
    WHERE leased_by = p_run AND state = 'leased';
END;
$$;

-- Settings change only from the console, where the change is logged with the account.
DROP FUNCTION change_setting(text, text, jsonb, text);

CREATE FUNCTION console_change_setting(p_token text, p_key text, p_value jsonb, p_reason text) RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run text := console_act(p_token, 'change setting', p_key, jsonb_build_object('value', p_value));
    old jsonb := setting(p_key);
BEGIN
    IF coalesce(btrim(p_reason), '') = '' THEN
        RAISE EXCEPTION 'say why the setting changes' USING ERRCODE = '22023';
    END IF;
    IF jsonb_typeof(old) IS DISTINCT FROM jsonb_typeof(p_value) THEN
        RAISE EXCEPTION 'setting % takes a % value', p_key, jsonb_typeof(old) USING ERRCODE = '22023';
    END IF;
    INSERT INTO setting_changes (key, old_value, new_value, run_id, reason) VALUES (p_key, old, p_value, run, p_reason);
    UPDATE settings SET value = p_value, updated_at = now(), updated_by = run WHERE key = p_key;
END;
$$;

CREATE FUNCTION console_plan_audits(p_token text, p_force boolean) RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
BEGIN
    RETURN plan_audits_for(console_act(p_token, 'plan audits', NULL, jsonb_build_object('force', p_force)), p_force);
END;
$$;

-- Audit planning, shared by the system worker (with a run token) and the console (with a session).
CREATE FUNCTION plan_audits_for(p_run text, p_force boolean) RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
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
                setting('audit.threshold.' || grp.type)::text::numeric, p_run);
        INSERT INTO audit_members (batch_id, revision_id, sampled)
        SELECT new_batch, r, row_number() OVER (ORDER BY random()) <= sample FROM unnest(grp.revisions) AS r;
        PERFORM enqueue(p_run, 'audit', 'audit:' || new_batch || ':' || m.revision_id,
                        jsonb_build_object('batch', new_batch), i.city_id, i.place_id, i.id, m.revision_id,
                        ARRAY[r.created_by_run], m.revision_id)
        FROM audit_members m JOIN revisions r ON r.id = m.revision_id JOIN items i ON i.id = r.item_id
        WHERE m.batch_id = new_batch AND m.sampled;
        created := created + 1;
    END LOOP;
    RETURN created;
END;
$$;

CREATE OR REPLACE FUNCTION plan_audits(p_token text, p_force boolean DEFAULT false) RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
BEGIN
    RETURN plan_audits_for((run_for(p_token, ARRAY['system'])).id, p_force);
END;
$$;

-- Measured accuracy (design.md, section 5.4): for each kind of check and model, how often its verdicts were
-- overturned by a later, higher-ranking verdict on the same claim or item (escalation, audit, or editor).
CREATE VIEW model_accuracy AS
WITH ranked AS (
    SELECT k.*, CASE k.kind WHEN 'editor' THEN 3 WHEN 'audit' THEN 2 WHEN 'escalation' THEN 1 ELSE 0 END AS rank,
           k.verdict IN ('supported', 'pass') AS positive
    FROM checks k WHERE k.kind <> 'tool'
),
judged AS (
    SELECT first.kind, first.model, first.positive,
           (SELECT later.positive FROM ranked later
            WHERE later.revision_id = first.revision_id AND later.claim_id IS NOT DISTINCT FROM first.claim_id
              AND later.rank > first.rank AND later.id > first.id
            ORDER BY later.rank DESC, later.id DESC LIMIT 1) AS final
    FROM ranked first WHERE first.rank < 3 AND first.model IS NOT NULL
)
SELECT kind, model, count(*) AS verdicts, count(final) AS judged,
       count(*) FILTER (WHERE final IS NOT NULL AND final <> positive) AS overturned,
       round(count(*) FILTER (WHERE final IS NOT NULL AND final <> positive)::numeric / nullif(count(final), 0), 4)
           AS error_rate
FROM judged GROUP BY kind, model;

-- Publish requests from the console are tasks the publisher service leases.
ALTER TABLE task_types DROP CONSTRAINT task_types_runner_check;
ALTER TABLE task_types ADD CONSTRAINT task_types_runner_check CHECK (runner IN ('worker', 'system', 'publisher'));
INSERT INTO task_types (name, runner, description) VALUES
    ('publish', 'publisher', 'Build, stage, check, and (unless only checking) promote the output.'),
    ('rollback', 'publisher', 'Point production back at the version before.');

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

-- The publisher closes its tasks with the outcome (publish and rollback results aren't revisions).
CREATE FUNCTION finish_task(p_token text, p_task text, p_result jsonb) RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['publisher']);
    task tasks := held_task(run, p_task);
BEGIN
    UPDATE tasks SET state = 'done', result = p_result, done_by = run.id, done_at = now(), leased_by = NULL,
                     leased_until = NULL
    WHERE id = task.id;
END;
$$;

CREATE FUNCTION console_request(p_token text, p_type text, p_input jsonb) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run text := console_act(p_token, 'request ' || p_type, NULL, p_input);
BEGIN
    IF p_type NOT IN ('publish', 'rollback') THEN
        RAISE EXCEPTION 'the console can''t request %', p_type USING ERRCODE = '22023';
    END IF;
    IF EXISTS (SELECT 1 FROM tasks WHERE type IN ('publish', 'rollback') AND state IN ('queued', 'leased')) THEN
        RAISE EXCEPTION 'a publish or rollback is already waiting' USING ERRCODE = 'P0001';
    END IF;
    RETURN enqueue(run, p_type, p_type || ':' || run || ':' || floor(extract(epoch FROM clock_timestamp()) * 1000),
                   p_input, NULL, NULL, NULL, NULL, '{}', NULL, 100);
END;
$$;

-- Queues research, writing, or translation work from the console.
CREATE FUNCTION console_queue(p_token text, p_type text, p_city bigint, p_place text, p_item text, p_input jsonb)
RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run text := console_act(p_token, 'queue ' || p_type, coalesce(p_place, p_item, p_city::text), p_input);
    item items := (SELECT i FROM items i WHERE i.id = p_item);
BEGIN
    IF p_type NOT IN ('write_story', 'write_guide', 'write_trail', 'translate', 'find_photos') THEN
        RAISE EXCEPTION 'the console can''t queue %', p_type USING ERRCODE = '22023';
    END IF;
    IF p_type = 'translate' AND (item.id IS NULL OR item.published_revision IS NULL) THEN
        RAISE EXCEPTION 'only published items are translated' USING ERRCODE = '22023';
    END IF;
    RETURN enqueue(run, p_type, p_type || ':' || coalesce(p_place, p_item, p_city::text) || ':'
                   || floor(extract(epoch FROM clock_timestamp()) * 1000),
                   coalesce(p_input, '{}'), coalesce(p_city, item.city_id), coalesce(p_place, item.place_id),
                   p_item, item.published_revision, '{}', NULL, 0);
END;
$$;

GRANT EXECUTE ON FUNCTION console_sign_in(text, text, integer), console_session(text), console_sign_out(text),
    console_retire(text, text, text), console_recheck(text, text, text),
    console_verdict(text, text, text, text, text), console_task(text, text, text), console_end_run(text, text),
    console_change_setting(text, text, jsonb, text), console_plan_audits(text, boolean),
    console_request(text, text, jsonb), console_queue(text, text, bigint, text, text, jsonb)
    TO psst_platform_console;
GRANT EXECUTE ON FUNCTION lease_task(text, text[], bigint), finish_task(text, text, jsonb) TO psst_platform_publisher;
GRANT EXECUTE ON FUNCTION lease_task(text, text[], bigint) TO psst_platform_worker, psst_platform_system;
SELECT apply_read_grants();
