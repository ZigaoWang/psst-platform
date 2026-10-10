-- A budget per city (decision 28): the harness stops a city's work before its spend reaches the city's budget; a city
-- without one gets nothing. Calibrations belong to no city and count only against the total.
SET search_path = psst, public;

INSERT INTO settings (key, value, note) VALUES
    ('harness.city_budgets_usd', '{"london": 8, "shanghai": 6}',
     'Most the harness may spend on each city in all, by slug; a city not listed gets nothing.');

CREATE OR REPLACE FUNCTION harness_spend(p_city bigint DEFAULT NULL) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
    SELECT jsonb_build_object(
        'total', coalesce(sum(cost_usd), 0),
        'city_total', coalesce(sum(cost_usd) FILTER (WHERE city_id = p_city), 0),
        'city_today', coalesce(sum(cost_usd) FILTER (WHERE city_id = p_city AND created_at >= date_trunc('day', now())), 0),
        'city_month', coalesce(sum(cost_usd) FILTER (WHERE city_id = p_city
                                                     AND created_at >= date_trunc('month', now())), 0),
        'city_budget', (SELECT setting('harness.city_budgets_usd') -> c.slug FROM cities c WHERE c.id = p_city))
    FROM harness_calls
$$;
