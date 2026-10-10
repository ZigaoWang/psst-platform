-- A research cell whose task failed or was cancelled goes back to open, and queueing it again brings that task back
-- with the model research is routed to now, instead of leaving the cell queued with nothing to work it.
SET search_path = psst, public;

CREATE OR REPLACE FUNCTION queue_research(p_token text, p_cells jsonb) RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    system runs := run_for(p_token, ARRAY['system']);
    entry jsonb;
    purpose_key text;
    queued integer := 0;
BEGIN
    FOR entry IN SELECT value FROM jsonb_array_elements(p_cells) LOOP
        CONTINUE WHEN (SELECT state FROM research_cells WHERE cell = entry ->> 'cell') <> 'open';
        purpose_key := 'research_cell:' || (entry ->> 'cell') || ':'
                       || (SELECT passes FROM research_cells WHERE cell = entry ->> 'cell');
        UPDATE tasks SET state = 'queued', attempts = 0, problem = NULL, model = task_model(type, input),
                         priority = coalesce((entry ->> 'priority')::integer, 0)
        WHERE purpose = purpose_key AND state IN ('cancelled', 'failed');
        IF NOT FOUND THEN
            PERFORM enqueue(system.id, 'research_cell', purpose_key, jsonb_build_object('cell', entry ->> 'cell'),
                            (SELECT city_id FROM research_cells WHERE cell = entry ->> 'cell'), NULL, NULL, NULL,
                            '{}', NULL, coalesce((entry ->> 'priority')::integer, 0));
        END IF;
        UPDATE research_cells SET state = 'queued' WHERE cell = entry ->> 'cell';
        queued := queued + 1;
    END LOOP;
    RETURN queued;
END;
$$;

CREATE FUNCTION release_research_cell() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
BEGIN
    UPDATE research_cells SET state = 'open' WHERE cell = NEW.input ->> 'cell' AND state = 'queued';
    RETURN NEW;
END;
$$;

CREATE TRIGGER research_task_ended AFTER UPDATE OF state ON tasks
FOR EACH ROW WHEN (NEW.type = 'research_cell' AND NEW.state IN ('failed', 'cancelled') AND OLD.state <> NEW.state)
EXECUTE FUNCTION release_research_cell();

-- Cells left queued by a research task that already failed or was cancelled.
UPDATE research_cells r SET state = 'open'
WHERE r.state = 'queued' AND NOT EXISTS (
    SELECT 1 FROM tasks t WHERE t.type = 'research_cell' AND t.input ->> 'cell' = r.cell AND t.state IN ('queued', 'leased'));
