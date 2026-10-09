-- The model a task goes to, in one place: its type's routing, except that research on a dense cell (many open
-- leads) goes to the model set for dense cells (decision 24). Leasing, the queue command, and the console use it.
SET search_path = psst, public;

INSERT INTO settings (key, value, note) VALUES
    ('routing.research_cell_dense', '"claude-opus-5-5"', 'Model for researching a dense cell (decision 24).'),
    ('research.dense_leads', '100', 'Open leads at or above which a cell counts as dense.');

CREATE FUNCTION task_model(p_type text, p_input jsonb) RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
    SELECT CASE
        WHEN p_type = 'research_cell' AND (
            SELECT count(*) FROM leads WHERE cell = p_input ->> 'cell' AND status IN ('open', 'later'))
            >= setting('research.dense_leads')::text::integer
        THEN setting('routing.research_cell_dense') #>> '{}'
        ELSE (SELECT value #>> '{}' FROM settings WHERE key = 'routing.' || p_type)
    END
$$;
GRANT EXECUTE ON FUNCTION task_model(text, jsonb) TO psst_platform_worker, psst_platform_console;

CREATE OR REPLACE FUNCTION lease_task(p_token text, p_types text[], p_city bigint DEFAULT NULL) RETURNS SETOF tasks
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['worker', 'system', 'publisher']);
    task tasks;
BEGIN
    PERFORM expire_leases();
    SELECT t.* INTO task FROM tasks t JOIN task_types y ON y.name = t.type
    WHERE t.state = 'queued' AND t.type = ANY(p_types) AND y.active
      AND (p_city IS NULL OR t.city_id = p_city)
      AND y.runner = run.kind
      AND (run.kind <> 'worker' OR task_model(t.type, t.input) = run.model)
      AND NOT run.id = ANY(t.exclude_runs)
      AND (t.place_id IS NULL OR t.type IN ('tool_check', 'resolve_places', 'relink_place')
           OR EXISTS (SELECT 1 FROM places p WHERE p.id = t.place_id AND p.state = 'active'))
      AND (t.type <> 'review' OR NOT EXISTS (
            SELECT 1 FROM jsonb_array_elements_text(t.input -> 'revisions') AS r(id)
            JOIN revisions v ON v.id = r.id JOIN items i ON i.id = v.item_id JOIN places p ON p.id = i.place_id
            WHERE p.state = 'pending'))
      AND (t.independence IS NULL OR NOT EXISTS (
            SELECT 1 FROM task_leases l JOIN tasks o ON o.id = l.task_id
            WHERE l.run_id = run.id AND o.independence = t.independence))
    ORDER BY t.priority DESC, t.created_at, t.id
    FOR UPDATE OF t SKIP LOCKED
    LIMIT 1;
    IF NOT FOUND THEN
        RETURN;
    END IF;
    UPDATE tasks SET state = 'leased', leased_by = run.id, model = coalesce(run.model, model),
                     attempts = attempts + 1, problem = NULL,
                     leased_until = now() + make_interval(mins => lease_minutes(type))
    WHERE id = task.id RETURNING * INTO task;
    INSERT INTO task_leases (task_id, run_id) VALUES (task.id, run.id);
    RETURN NEXT task;
END;
$$;
