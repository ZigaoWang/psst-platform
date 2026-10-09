-- Who can read what (design.md, section 14). No login role can write a table directly: every change goes
-- through a function. Reads are granted by one function that later migrations call again after adding tables,
-- so the rules live in one place.
SET search_path = psst, public;

GRANT USAGE ON SCHEMA psst TO psst_platform_system, psst_platform_worker, psst_platform_publisher,
    psst_platform_console, psst_platform_api;

-- Tables only some roles read. Everything not listed is readable by the system, worker, publisher, and
-- console roles. `runs` is readable without its token hashes.
CREATE TABLE read_limits (
    table_name text PRIMARY KEY,
    readers    text[] NOT NULL
);

CREATE FUNCTION apply_read_grants() RETURNS void
LANGUAGE plpgsql VOLATILE SET search_path = psst, public, pg_temp AS $$
DECLARE
    tbl text;
    reader text;
    all_readers constant text[] := ARRAY['psst_platform_system', 'psst_platform_worker', 'psst_platform_publisher',
                                         'psst_platform_console'];
    readers text[];
BEGIN
    FOR tbl IN SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
               WHERE n.nspname = 'psst' AND c.relkind IN ('r', 'v', 'p', 'm') LOOP
        readers := coalesce((SELECT l.readers FROM read_limits l WHERE l.table_name = tbl), all_readers);
        FOREACH reader IN ARRAY all_readers LOOP
            EXECUTE format('REVOKE ALL ON psst.%I FROM %I', tbl, reader);
        END LOOP;
        IF tbl = 'runs' THEN
            FOREACH reader IN ARRAY readers LOOP
                EXECUTE format('GRANT SELECT (id, kind, model, operator, started_at, ended_at, notes) ON psst.runs TO %I',
                               reader);
            END LOOP;
        ELSE
            FOREACH reader IN ARRAY readers LOOP
                EXECUTE format('GRANT SELECT ON psst.%I TO %I', tbl, reader);
            END LOOP;
        END IF;
    END LOOP;
END;
$$;

INSERT INTO read_limits VALUES
    ('read_limits', ARRAY[]::text[]),
    ('lifecycle_moves', ARRAY['psst_platform_system', 'psst_platform_console']),
    ('setting_changes', ARRAY['psst_platform_system', 'psst_platform_console']),
    ('reports', ARRAY['psst_platform_system', 'psst_platform_worker', 'psst_platform_console']),
    ('demand', ARRAY['psst_platform_system', 'psst_platform_console']);

SELECT apply_read_grants();

GRANT EXECUTE ON FUNCTION start_run(text, text, text, text), end_run(text, text), setting(text)
    TO psst_platform_system, psst_platform_worker, psst_platform_publisher, psst_platform_console;
GRANT EXECUTE ON FUNCTION change_setting(text, text, jsonb, text) TO psst_platform_console;
