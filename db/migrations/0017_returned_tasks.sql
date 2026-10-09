-- A run that gives a task back is not handed the same task again: it already judged it couldn't do it well.
SET search_path = psst, public;

CREATE OR REPLACE FUNCTION return_task(p_token text, p_task text, p_problem text) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['worker', 'system']);
    task tasks := held_task(run, p_task);
    next_state text := CASE WHEN task.attempts >= setting('lease.max_attempts')::text::integer THEN 'failed'
                            ELSE 'queued' END;
BEGIN
    UPDATE tasks SET state = next_state, leased_by = NULL, leased_until = NULL, problem = p_problem,
                     exclude_runs = CASE WHEN run.kind = 'worker' THEN array_append(exclude_runs, run.id)
                                         ELSE exclude_runs END
    WHERE id = task.id;
    RETURN next_state;
END;
$$;
