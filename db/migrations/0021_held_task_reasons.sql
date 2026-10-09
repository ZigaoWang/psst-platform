-- A worker whose task was cancelled or expired while it held it learns why, instead of a bare refusal.
SET search_path = psst, public;

CREATE OR REPLACE FUNCTION held_task(p_run runs, p_task text) RETURNS tasks
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    task tasks;
BEGIN
    SELECT * INTO task FROM tasks WHERE id = p_task FOR UPDATE;
    IF FOUND AND task.state = 'leased' AND task.leased_by = p_run.id THEN
        IF task.leased_until < now() THEN
            RAISE EXCEPTION 'the lease on task % has expired', p_task USING ERRCODE = '42501';
        END IF;
        RETURN task;
    END IF;
    IF FOUND AND task.state IN ('cancelled', 'queued', 'failed')
       AND EXISTS (SELECT 1 FROM task_leases WHERE task_id = p_task AND run_id = p_run.id) THEN
        RAISE EXCEPTION 'task % is no longer yours: %; nothing more to do for it', p_task,
            coalesce(task.problem, 'it is ' || task.state) USING ERRCODE = '42501';
    END IF;
    RAISE EXCEPTION 'task % isn''t leased to this run', p_task USING ERRCODE = '42501';
END;
$$;
