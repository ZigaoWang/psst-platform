-- Every kind of run ends itself, the publisher's included (it ran every minute and could not).
SET search_path = psst, public;

CREATE OR REPLACE FUNCTION end_run(p_token text, p_notes text DEFAULT NULL) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['worker', 'editor', 'system', 'publisher']);
BEGIN
    UPDATE tasks SET state = 'queued', leased_by = NULL, leased_until = NULL, problem = 'its run ended'
    WHERE leased_by = run.id AND state = 'leased';
    UPDATE runs SET ended_at = now(), notes = coalesce(nullif(p_notes, ''), notes) WHERE id = run.id;
    RETURN run.id;
END;
$$;
