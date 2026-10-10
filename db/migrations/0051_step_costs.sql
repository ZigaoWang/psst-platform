-- The cost of each step per place written (decision 34): kept as a view the console shows permanently, so cost and
-- time can't creep back unnoticed. Reasoning tokens are recorded apart from the rest of the output.
SET search_path = psst, public;

ALTER TABLE harness_calls ADD COLUMN reasoning_tokens integer NOT NULL DEFAULT 0;

CREATE OR REPLACE FUNCTION record_harness_call(p_token text, p_call jsonb) RETURNS bigint
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['worker', 'system']);
    new_id bigint;
BEGIN
    INSERT INTO harness_calls (run_id, task_id, city_id, step, provider, model, prompt_version, tools_version,
                               replay_of, request, response, error, input_tokens, cached_tokens, output_tokens,
                               reasoning_tokens, cost_usd, latency_ms)
    VALUES (run.id, p_call ->> 'task', (p_call ->> 'city')::bigint, p_call ->> 'step', p_call ->> 'provider',
            p_call ->> 'model', p_call ->> 'prompt_version', p_call ->> 'tools_version',
            (p_call ->> 'replay_of')::bigint, p_call -> 'request', p_call -> 'response', p_call ->> 'error',
            coalesce((p_call ->> 'input_tokens')::integer, 0), coalesce((p_call ->> 'cached_tokens')::integer, 0),
            coalesce((p_call ->> 'output_tokens')::integer, 0), coalesce((p_call ->> 'reasoning_tokens')::integer, 0),
            coalesce((p_call ->> 'cost_usd')::numeric, 0), coalesce((p_call ->> 'latency_ms')::integer, 0))
    RETURNING id INTO new_id;
    INSERT INTO harness_tool_calls (call_id, tool, input, output, error, latency_ms)
    SELECT new_id, t ->> 'tool', t -> 'input', t -> 'output', t ->> 'error', coalesce((t ->> 'latency_ms')::integer, 0)
    FROM jsonb_array_elements(coalesce(p_call -> 'tools', '[]')) t;
    RETURN new_id;
END;
$$;

-- Per day, step, and model: calls, tokens, cost, seconds, and fix rounds, beside the places written that day.
CREATE VIEW harness_step_costs AS
    WITH calls AS (
        SELECT h.*, date_trunc('day', h.created_at)::date AS day,
               (SELECT count(*) FROM jsonb_array_elements(h.request -> 'messages') m
                WHERE m ->> 'role' = 'user' AND m ->> 'content' LIKE 'Not submitted%') > 0 AS fix_round,
               coalesce((SELECT sum(t.latency_ms) FROM harness_tool_calls t WHERE t.call_id = h.id), 0) AS tool_ms
        FROM harness_calls h)
    SELECT day, step, model, count(*) AS calls, count(*) FILTER (WHERE fix_round) AS fix_rounds,
           sum(input_tokens) AS input_tokens, sum(cached_tokens) AS cached_tokens, sum(output_tokens) AS output_tokens,
           sum(reasoning_tokens) AS reasoning_tokens, sum(cost_usd) AS cost_usd,
           round(sum(latency_ms) / 1000.0) AS model_seconds, round(sum(tool_ms) / 1000.0) AS tool_seconds,
           (SELECT count(DISTINCT place_id) FROM harness_calls w
            WHERE w.place_id IS NOT NULL AND date_trunc('day', w.created_at)::date = calls.day) AS places_written
    FROM calls GROUP BY day, step, model;

SELECT apply_read_grants();
