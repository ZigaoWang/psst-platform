-- A spending window for an unattended run (decision 36): a cap on what the harness spends from a given time, the task
-- types it works, and the two reasons it stops on its own: cost per place still standing, and a pass whose places
-- mostly fail.
SET search_path = psst, public;

INSERT INTO settings (key, value, note) VALUES
    ('harness.window', 'null', 'An unattended run''s window: {"from": <time>, "usd": <cap>}. Spend since then may not pass the cap.'),
    ('harness.work_types', 'null', 'The task types the harness service works, in its order; null for all of them.'),
    ('harness.max_usd_per_place', 'null', 'The service stops when the window''s spend per place still standing passes this.'),
    ('harness.max_failed_share', 'null', 'The service stops when more than this share of one pass''s places fail.');

-- What the window has spent, and the places written in it that still stand (checking, accepted, or published) and
-- that failed (every item sent back).
CREATE FUNCTION harness_window() RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
    WITH w AS (SELECT (setting('harness.window') ->> 'from')::timestamptz AS since,
                      (setting('harness.window') ->> 'usd')::numeric AS usd),
    placed AS (
        SELECT i.place_id, bool_or(i.state IN ('checking', 'accepted', 'published')) AS standing
        FROM items i, w WHERE i.created_at >= w.since AND i.type IN ('story', 'guide') GROUP BY i.place_id)
    SELECT CASE WHEN w.since IS NULL THEN NULL ELSE jsonb_build_object(
        'from', w.since, 'usd', w.usd,
        'spent', (SELECT coalesce(sum(cost_usd), 0) FROM harness_calls WHERE created_at >= w.since),
        'places', (SELECT count(*) FROM placed WHERE standing),
        'failed', (SELECT count(*) FROM placed WHERE NOT standing)) END
    FROM w
$$;

GRANT EXECUTE ON FUNCTION harness_window() TO psst_platform_worker, psst_platform_system, psst_platform_console;
