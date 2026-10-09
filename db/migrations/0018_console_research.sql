-- Queueing research from the console: sweeping leads needs the network, so the console queues a system task and the
-- system worker sweeps and queues the cells.
SET search_path = psst, public;

INSERT INTO task_types (name, runner, description) VALUES
    ('queue_research', 'system', 'Sweep leads for a city''s most wanted open cells and queue their research.');

CREATE FUNCTION console_queue_research(p_token text, p_city bigint, p_cells integer) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run text := console_act(p_token, 'queue research', p_city::text, jsonb_build_object('cells', p_cells));
BEGIN
    IF p_cells NOT BETWEEN 1 AND 50 THEN
        RAISE EXCEPTION 'queue between 1 and 50 cells at a time' USING ERRCODE = '22023';
    END IF;
    RETURN enqueue(run, 'queue_research', 'queue_research:' || p_city || ':' ||
                   floor(extract(epoch FROM clock_timestamp()) * 1000),
                   jsonb_build_object('city', (SELECT slug FROM cities WHERE id = p_city), 'cells', p_cells),
                   p_city, NULL, NULL, NULL, '{}', NULL, 50);
END;
$$;

GRANT EXECUTE ON FUNCTION console_queue_research(text, bigint, integer) TO psst_platform_console;
