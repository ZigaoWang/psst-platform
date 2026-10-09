-- Schema, ids, runs, and settings. Text columns with a fixed set of values use CHECK constraints, so adding a
-- value later is a one-line migration. Every function that writes runs with definer rights, pins its search
-- path, and is executable only by the roles granted it in the access migration.

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA psst;
REVOKE ALL ON SCHEMA psst FROM PUBLIC;
-- Functions are executable only where granted. (A per-schema default can't revoke the global grant to PUBLIC.)
ALTER DEFAULT PRIVILEGES REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
SET search_path = psst, public;

-- A permanent id: a prefix and random Crockford base32 (no i, l, o, or u). 256 is a multiple of 32, so taking
-- each random byte modulo 32 keeps every character equally likely.
CREATE FUNCTION new_id(prefix text, len integer DEFAULT 10) RETURNS text
LANGUAGE plpgsql VOLATILE SET search_path = psst, public AS $$
DECLARE
    alphabet constant text := '0123456789abcdefghjkmnpqrstvwxyz';
    bytes bytea := gen_random_bytes(len);
    result text := prefix || '_';
BEGIN
    FOR i IN 0 .. len - 1 LOOP
        result := result || substr(alphabet, get_byte(bytes, i) % 32 + 1, 1);
    END LOOP;
    RETURN result;
END;
$$;

CREATE FUNCTION id_pattern(prefix text, len integer DEFAULT 10) RETURNS text
LANGUAGE sql IMMUTABLE AS $$ SELECT '^' || prefix || '_[0-9a-hjkmnp-tv-z]{' || len || '}$' $$;

CREATE FUNCTION touch_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

-- Tables whose rows are history: written once, never changed or removed.
CREATE FUNCTION refuse_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% rows are never changed or deleted', TG_TABLE_NAME USING ERRCODE = 'P0001';
END;
$$;

-- Runs ----------------------------------------------------------------------------------------------------

-- One worker, editor, or system process doing a batch of work. The token is shown once when the run starts;
-- only its hash is kept. Every write function takes the token and records the run.
CREATE TABLE runs (
    id         text PRIMARY KEY CHECK (id ~ id_pattern('ru')),
    kind       text NOT NULL CHECK (kind IN ('worker', 'editor', 'system')),
    model      text CHECK (model ~ '^[a-z0-9][a-z0-9.-]*$'),
    operator   text NOT NULL CHECK (operator <> ''),
    token_hash bytea NOT NULL UNIQUE,
    started_at timestamptz NOT NULL DEFAULT now(),
    ended_at   timestamptz,
    notes      text,
    CHECK (kind <> 'worker' OR model IS NOT NULL)
);
CREATE INDEX runs_started_idx ON runs (started_at DESC);
CREATE INDEX runs_open_idx ON runs (kind) WHERE ended_at IS NULL;

-- The run kind each login role may start. The schema owner (migrations, tests, maintenance) may start any.
CREATE FUNCTION caller_may_run(p_kind text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = psst, pg_temp AS $$
    SELECT session_user = (SELECT nspowner::regrole::text FROM pg_namespace WHERE nspname = 'psst')
        OR pg_has_role(session_user, CASE p_kind WHEN 'worker' THEN 'psst_platform_worker'
                                                 WHEN 'system' THEN 'psst_platform_system'
                                                 WHEN 'editor' THEN 'psst_platform_console' END, 'MEMBER')
$$;

CREATE FUNCTION start_run(p_kind text, p_operator text, p_model text DEFAULT NULL, p_notes text DEFAULT NULL)
RETURNS TABLE (run_id text, token text)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    new_token text := encode(gen_random_bytes(32), 'hex');
BEGIN
    IF NOT caller_may_run(p_kind) THEN
        RAISE EXCEPTION 'this login can''t start a % run', p_kind USING ERRCODE = '42501';
    END IF;
    run_id := new_id('ru');
    INSERT INTO runs (id, kind, model, operator, token_hash, notes)
    VALUES (run_id, p_kind, p_model, p_operator, digest(new_token, 'sha256'), nullif(p_notes, ''));
    token := new_token;
    RETURN NEXT;
END;
$$;

-- The open run a token belongs to, if the caller may act for that kind of run.
CREATE FUNCTION run_for(p_token text, p_kinds text[] DEFAULT ARRAY['worker', 'editor', 'system']) RETURNS runs
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    caller runs;
BEGIN
    SELECT * INTO caller FROM runs WHERE token_hash = digest(coalesce(p_token, ''), 'sha256');
    IF NOT FOUND THEN
        RAISE EXCEPTION 'unknown run token' USING ERRCODE = '28000';
    END IF;
    IF caller.ended_at IS NOT NULL THEN
        RAISE EXCEPTION 'run % has ended', caller.id USING ERRCODE = '28000';
    END IF;
    IF NOT caller.kind = ANY(p_kinds) OR NOT caller_may_run(caller.kind) THEN
        RAISE EXCEPTION 'a % run can''t do this', caller.kind USING ERRCODE = '42501';
    END IF;
    RETURN caller;
END;
$$;

CREATE FUNCTION end_run(p_token text, p_notes text DEFAULT NULL) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token);
BEGIN
    UPDATE runs SET ended_at = now(), notes = coalesce(nullif(p_notes, ''), notes) WHERE id = run.id;
    RETURN run.id;
END;
$$;

-- Settings -------------------------------------------------------------------------------------------------

-- Values editors tune from the console: audit thresholds, model routing, lease lengths. Content rules live in
-- the rulebook instead (decisions.md, 9).
CREATE TABLE settings (
    key        text PRIMARY KEY CHECK (key ~ '^[a-z_]+(\.[a-z_]+)*$'),
    value      jsonb NOT NULL,
    note       text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by text REFERENCES runs
);

CREATE TABLE setting_changes (
    id        bigserial PRIMARY KEY,
    key       text NOT NULL REFERENCES settings,
    old_value jsonb,
    new_value jsonb NOT NULL,
    run_id    text NOT NULL REFERENCES runs,
    reason    text NOT NULL CHECK (reason <> ''),
    at        timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER setting_changes_history BEFORE UPDATE OR DELETE ON setting_changes
    FOR EACH ROW EXECUTE FUNCTION refuse_change();

CREATE FUNCTION setting(p_key text) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = psst, pg_temp AS $$
DECLARE
    current jsonb;
BEGIN
    SELECT value INTO current FROM settings WHERE key = p_key;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'no setting %', p_key USING ERRCODE = 'P0002';
    END IF;
    RETURN current;
END;
$$;

CREATE FUNCTION change_setting(p_token text, p_key text, p_value jsonb, p_reason text) RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['editor']);
    old jsonb := setting(p_key);
BEGIN
    IF jsonb_typeof(old) IS DISTINCT FROM jsonb_typeof(p_value) THEN
        RAISE EXCEPTION 'setting % takes a % value', p_key, jsonb_typeof(old) USING ERRCODE = '22023';
    END IF;
    INSERT INTO setting_changes (key, old_value, new_value, run_id, reason) VALUES (p_key, old, p_value, run.id, p_reason);
    UPDATE settings SET value = p_value, updated_at = now(), updated_by = run.id WHERE key = p_key;
END;
$$;

INSERT INTO settings (key, value, note) VALUES
    ('audit.threshold.story', '0.02', 'Highest error rate a story audit batch may have and pass (1 in 50).'),
    ('audit.threshold.trail', '0.02', 'Highest error rate a trail audit batch may have and pass (1 in 50).'),
    ('audit.threshold.guide', '0.0333', 'Highest error rate a guide audit batch may have and pass (1 in 30).'),
    ('audit.threshold.photo', '0.0333', 'Highest error rate a photo audit batch may have and pass (1 in 30).'),
    ('audit.threshold.translation', '0.0333', 'Highest error rate a translation audit batch may have and pass (1 in 30).'),
    ('audit.min_batch', '30', 'Fewest accepted revisions an audit batch waits for, unless nothing else is waiting.'),
    ('audit.min_sample', '30', 'Fewest revisions sampled from a batch (all of them when the batch is smaller).'),
    ('audit.extra_sample_rate', '0.05', 'Share of a batch beyond the first 30 revisions that is also sampled.');
