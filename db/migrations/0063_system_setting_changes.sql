-- Settings changed from the server (the harness's routing, budgets, and windows) are recorded with their reason, as
-- the console's are: a system run may change a setting through the same function.
SET search_path = psst, public;

CREATE OR REPLACE FUNCTION change_setting(p_token text, p_key text, p_value jsonb, p_reason text) RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['editor', 'system']);
    old jsonb := setting(p_key);
BEGIN
    IF jsonb_typeof(old) IS DISTINCT FROM jsonb_typeof(p_value) AND 'null' NOT IN (jsonb_typeof(old), jsonb_typeof(p_value)) THEN
        RAISE EXCEPTION 'setting % takes a % value', p_key, jsonb_typeof(old) USING ERRCODE = '22023';
    END IF;
    IF coalesce(trim(p_reason), '') = '' THEN
        RAISE EXCEPTION 'say why the setting changes' USING ERRCODE = '22023';
    END IF;
    INSERT INTO setting_changes (key, old_value, new_value, run_id, reason) VALUES (p_key, old, p_value, run.id, p_reason);
    UPDATE settings SET value = p_value, updated_at = now(), updated_by = run.id WHERE key = p_key;
END;
$$;

GRANT EXECUTE ON FUNCTION change_setting(text, text, jsonb, text) TO psst_platform_system;
