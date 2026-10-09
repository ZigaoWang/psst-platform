-- Ending a run gives back any task it still holds, so the task doesn't wait for its lease to run out.
SET search_path = psst, public;

CREATE OR REPLACE FUNCTION end_run(p_token text, p_notes text DEFAULT NULL) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token);
BEGIN
    UPDATE tasks SET state = 'queued', leased_by = NULL, leased_until = NULL, problem = 'its run ended'
    WHERE leased_by = run.id AND state = 'leased';
    UPDATE runs SET ended_at = now(), notes = coalesce(nullif(p_notes, ''), notes) WHERE id = run.id;
    RETURN run.id;
END;
$$;
