-- The harness service, starting, ends the runs an earlier start of it left open (it was stopped before it could end
-- them) and puts their tasks back in the queue, so a restart never leaves a cell leased to a run that is gone. One
-- service runs at a time.
SET search_path = psst, public;

CREATE FUNCTION end_earlier_service_runs(p_token text) RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    system runs := run_for(p_token, ARRAY['system']);
    ended integer;
BEGIN
    UPDATE tasks SET state = 'queued', leased_by = NULL, leased_until = NULL, problem = 'its run ended'
    WHERE state = 'leased' AND leased_by IN (
        SELECT id FROM runs WHERE notes IN ('harness service', 'research planning for the harness service')
          AND ended_at IS NULL AND id <> system.id);
    UPDATE runs SET ended_at = now()
    WHERE notes IN ('harness service', 'research planning for the harness service') AND ended_at IS NULL
      AND id <> system.id;
    GET DIAGNOSTICS ended = ROW_COUNT;
    RETURN ended;
END;
$$;

GRANT EXECUTE ON FUNCTION end_earlier_service_runs(text) TO psst_platform_system;
