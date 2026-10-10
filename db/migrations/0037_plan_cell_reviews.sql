-- plan_reviews also starts the review of a finished research cell whose items wait without one (a rule recheck sent
-- them back, or their review was replanned), through ensure_review, which batches the cell and waits until every
-- item in it has passed its tool checks.
SET search_path = psst, public;

CREATE OR REPLACE FUNCTION plan_reviews(p_token text) RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['system']);
    size integer := setting('review.max_batch')::text::integer;
    waiting record;
    planned integer := 0;
BEGIN
    FOR waiting IN
        SELECT min(r.id) AS revision
        FROM items i JOIN revisions r ON r.id = i.current_revision JOIN tasks w ON w.id = r.created_by_task
        WHERE i.state = 'checking' AND i.type IN ('story', 'guide', 'trail')
          AND w.type = 'research_cell' AND w.state = 'done'
          AND NOT EXISTS (SELECT 1 FROM tasks t WHERE t.type = 'review' AND t.state IN ('queued', 'leased')
                          AND t.input -> 'revisions' ? r.id)
          AND evaluate(r.id) ->> 'missing' = 'review'
        GROUP BY w.id
    LOOP
        IF ensure_review(run.id, waiting.revision) IS NOT NULL THEN
            planned := planned + 1;
        END IF;
    END LOOP;
    FOR waiting IN
        WITH ready AS (
            SELECT r.id, r.created_by_run, i.city_id
            FROM items i JOIN revisions r ON r.id = i.current_revision
            WHERE i.state = 'checking' AND i.type IN ('story', 'guide', 'trail')
              AND NOT EXISTS (SELECT 1 FROM tasks t WHERE t.id = r.created_by_task AND t.type = 'research_cell')
              AND NOT EXISTS (SELECT 1 FROM tasks t WHERE t.type = 'review' AND t.state IN ('queued', 'leased')
                              AND t.input -> 'revisions' ? r.id)
              AND evaluate(r.id) ->> 'missing' = 'review'),
        numbered AS (SELECT *, (row_number() OVER (PARTITION BY city_id ORDER BY id) - 1) / size AS chunk FROM ready)
        SELECT city_id, array_agg(id ORDER BY id) AS batch, array_agg(DISTINCT created_by_run) AS writers
        FROM numbered GROUP BY city_id, chunk
    LOOP
        PERFORM enqueue(run.id, 'review', 'review:' || waiting.batch[1] || ':' ||
                        floor(extract(epoch FROM clock_timestamp()) * 1000),
                        jsonb_build_object('revisions', to_jsonb(waiting.batch)), waiting.city_id, NULL, NULL, NULL,
                        waiting.writers, NULL, 10);
        planned := planned + 1;
    END LOOP;
    RETURN planned;
END;
$$;
