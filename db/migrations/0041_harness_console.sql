-- The console's Harness section: a budget that starts unset (null) can be set to a number and cleared again, and the
-- harness records the credit its provider reports so the console can show it without holding the key.
SET search_path = psst, public;

CREATE OR REPLACE FUNCTION change_setting(p_token text, p_key text, p_value jsonb, p_reason text) RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['editor']);
    old jsonb := setting(p_key);
BEGIN
    IF jsonb_typeof(old) IS DISTINCT FROM jsonb_typeof(p_value) AND 'null' NOT IN (jsonb_typeof(old), jsonb_typeof(p_value)) THEN
        RAISE EXCEPTION 'setting % takes a % value', p_key, jsonb_typeof(old) USING ERRCODE = '22023';
    END IF;
    INSERT INTO setting_changes (key, old_value, new_value, run_id, reason) VALUES (p_key, old, p_value, run.id, p_reason);
    UPDATE settings SET value = p_value, updated_at = now(), updated_by = run.id WHERE key = p_key;
END;
$$;

INSERT INTO settings (key, value, note) VALUES
    ('harness.credit', 'null', 'What the model provider last reported: the key''s spend and the account''s credit left.');

CREATE FUNCTION record_harness_credit(p_token text, p_credit jsonb) RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['worker', 'system']);
BEGIN
    UPDATE settings SET value = p_credit || jsonb_build_object('at', now()), updated_at = now(), updated_by = run.id
    WHERE key = 'harness.credit';
END;
$$;

GRANT EXECUTE ON FUNCTION record_harness_credit(text, jsonb) TO psst_platform_worker, psst_platform_system;
