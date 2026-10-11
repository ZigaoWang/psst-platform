-- A calibration marks one version of the golden set. When the set changes (an editor's mark, or the constructed
-- negatives rebuilt), calibrations still waiting for the old set are cancelled, instead of being leased, marked at a
-- cost, and refused.
SET search_path = psst, public;

CREATE FUNCTION cancel_stale_calibrations() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
BEGIN
    UPDATE tasks SET state = 'cancelled', problem = 'the golden set changed since it was queued'
    WHERE type = 'calibrate' AND state = 'queued' AND input ->> 'golden_version' IS DISTINCT FROM golden_version();
    RETURN NULL;
END;
$$;

CREATE TRIGGER calibrations_follow_golden AFTER INSERT OR UPDATE OR DELETE ON golden_stories
FOR EACH STATEMENT EXECUTE FUNCTION cancel_stale_calibrations();

UPDATE tasks SET state = 'cancelled', problem = 'the golden set changed since it was queued'
WHERE type = 'calibrate' AND state = 'queued' AND input ->> 'golden_version' IS DISTINCT FROM golden_version();
