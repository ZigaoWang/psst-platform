-- The harness (decision 28): API models do the judgment steps, each call traced with its tokens and cost, under
-- an enforced budget. A calibration can name the model it measures, so a bake-off measures every candidate against
-- the golden set the same way.
SET search_path = psst, public;

-- A harness run names its model as <provider>:<model>, such as openrouter:z-ai/glm-5.3-flash:batch.
ALTER TABLE runs DROP CONSTRAINT runs_model_check;
ALTER TABLE runs ADD CONSTRAINT runs_model_check
    CHECK (model ~ '^[a-z0-9][a-z0-9.-]*(:[a-z0-9][a-z0-9./_:-]*)?$');

CREATE TABLE harness_calls (
    id              bigserial PRIMARY KEY,
    run_id          text NOT NULL REFERENCES runs,
    task_id         text REFERENCES tasks,
    city_id         bigint REFERENCES cities,
    step            text NOT NULL,
    provider        text NOT NULL,
    model           text NOT NULL,
    prompt_version  text,
    tools_version   text,
    replay_of       bigint REFERENCES harness_calls,
    request         jsonb NOT NULL,
    response        jsonb,
    error           text,
    input_tokens    integer NOT NULL DEFAULT 0,
    cached_tokens   integer NOT NULL DEFAULT 0,
    output_tokens   integer NOT NULL DEFAULT 0,
    cost_usd        numeric(12, 6) NOT NULL DEFAULT 0,
    latency_ms      integer NOT NULL DEFAULT 0,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX harness_calls_task_idx ON harness_calls (task_id);
CREATE INDEX harness_calls_day_idx ON harness_calls (created_at);

CREATE TABLE harness_tool_calls (
    id          bigserial PRIMARY KEY,
    call_id     bigint NOT NULL REFERENCES harness_calls,
    tool        text NOT NULL,
    input       jsonb NOT NULL,
    output      jsonb,
    error       text,
    latency_ms  integer NOT NULL DEFAULT 0,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX harness_tool_calls_call_idx ON harness_tool_calls (call_id);

INSERT INTO settings (key, value, note) VALUES
    ('harness.budget_usd', '18', 'Total the harness may spend through its API key; it pauses before going past it.'),
    ('harness.city_daily_usd', 'null', 'Most the harness may spend on one city in a day; null until set.'),
    ('harness.city_monthly_usd', 'null', 'Most the harness may spend on one city in a month; null until set.'),
    ('harness.paused_cities', '[]', 'City slugs the harness leaves alone.'),
    ('harness.paused', 'false', 'Whether the harness is paused everywhere (set when a budget is reached).');

CREATE OR REPLACE FUNCTION task_model(p_type text, p_input jsonb) RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
    SELECT CASE
        WHEN p_type = 'research_cell' AND (
            SELECT count(*) FROM leads WHERE cell = p_input ->> 'cell' AND status IN ('open', 'later'))
            >= setting('research.dense_leads')::text::integer
        THEN setting('routing.research_cell_dense') #>> '{}'
        WHEN p_type = 'calibrate' THEN coalesce(p_input ->> 'model', setting('routing.review') #>> '{}')
        ELSE (SELECT value #>> '{}' FROM settings WHERE key = 'routing.' || p_type)
    END
$$;

-- Recording a call is the harness's own business; it runs as a worker.
CREATE FUNCTION record_harness_call(p_token text, p_call jsonb) RETURNS bigint
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['worker', 'system']);
    new_id bigint;
BEGIN
    INSERT INTO harness_calls (run_id, task_id, city_id, step, provider, model, prompt_version, tools_version,
                               replay_of, request, response, error, input_tokens, cached_tokens, output_tokens,
                               cost_usd, latency_ms)
    VALUES (run.id, p_call ->> 'task', (p_call ->> 'city')::bigint, p_call ->> 'step', p_call ->> 'provider',
            p_call ->> 'model', p_call ->> 'prompt_version', p_call ->> 'tools_version',
            (p_call ->> 'replay_of')::bigint, p_call -> 'request', p_call -> 'response', p_call ->> 'error',
            coalesce((p_call ->> 'input_tokens')::integer, 0), coalesce((p_call ->> 'cached_tokens')::integer, 0),
            coalesce((p_call ->> 'output_tokens')::integer, 0), coalesce((p_call ->> 'cost_usd')::numeric, 0),
            coalesce((p_call ->> 'latency_ms')::integer, 0))
    RETURNING id INTO new_id;
    INSERT INTO harness_tool_calls (call_id, tool, input, output, error, latency_ms)
    SELECT new_id, t ->> 'tool', t -> 'input', t -> 'output', t ->> 'error', coalesce((t ->> 'latency_ms')::integer, 0)
    FROM jsonb_array_elements(coalesce(p_call -> 'tools', '[]')) t;
    RETURN new_id;
END;
$$;

-- What the harness has spent: in all, and per city today and this month.
CREATE FUNCTION harness_spend(p_city bigint DEFAULT NULL) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
    SELECT jsonb_build_object(
        'total', coalesce(sum(cost_usd), 0),
        'city_today', coalesce(sum(cost_usd) FILTER (WHERE city_id = p_city AND created_at >= date_trunc('day', now())), 0),
        'city_month', coalesce(sum(cost_usd) FILTER (WHERE city_id = p_city
                                                     AND created_at >= date_trunc('month', now())), 0))
    FROM harness_calls
$$;

-- A calibration of any model against the golden set, for the bake-off: both folds, for the current review prompt
-- and golden bar.
CREATE FUNCTION queue_calibration(p_token text, p_model text, p_prompt text, p_bar text) RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['system']);
    golden text := golden_version();
    queued integer := 0;
BEGIN
    FOR f IN 0 .. 1 LOOP
        IF enqueue(run.id, 'calibrate', concat_ws(':', 'calibrate', golden, p_prompt, coalesce(p_bar, 'none'), p_model, f),
                   jsonb_build_object('fold', f, 'model', p_model, 'prompt_version', p_prompt, 'bar_version', p_bar,
                                      'golden_version', golden),
                   NULL, NULL, NULL, NULL, '{}', NULL, 30) IS NOT NULL THEN
            queued := queued + 1;
        END IF;
    END LOOP;
    RETURN queued;
END;
$$;

GRANT EXECUTE ON FUNCTION queue_calibration(text, text, text, text) TO psst_platform_system;

GRANT EXECUTE ON FUNCTION record_harness_call(text, jsonb) TO psst_platform_worker, psst_platform_system;
GRANT EXECUTE ON FUNCTION harness_spend(bigint) TO psst_platform_worker, psst_platform_system, psst_platform_console;
SELECT apply_read_grants();
