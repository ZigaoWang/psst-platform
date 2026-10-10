-- Reviews come in batches (decision 25): a research cell is reviewed together, and every other item waiting for a
-- review (a revision, an item sent back by a rule recheck) is batched with others of its city by plan_reviews, so a
-- reviewer reads the editor's examples once for many items and the 10 percent audit samples a real batch.
SET search_path = psst, public;

INSERT INTO settings (key, value, note) VALUES
    ('review.max_batch', '15', 'Most items in one review batch planned from revisions and rechecks.');

CREATE OR REPLACE FUNCTION ensure_review(p_run text, p_revision text) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    revision revisions := (SELECT r FROM revisions r WHERE r.id = p_revision);
    batch text[];
    writers text[];
    city bigint;
BEGIN
    IF EXISTS (SELECT 1 FROM tasks WHERE type = 'review' AND state IN ('queued', 'leased')
               AND input -> 'revisions' ? p_revision) THEN
        RETURN NULL;
    END IF;
    -- Research submitted place by place is reviewed together once the cell's final result is in.
    IF EXISTS (SELECT 1 FROM tasks t WHERE t.id = revision.created_by_task AND t.type = 'research_cell'
               AND t.state <> 'done') THEN
        RETURN NULL;
    END IF;
    -- A cell's research is reviewed together; anything else (a revision, a recheck) waits for plan_reviews, which
    -- batches it with other waiting items of its city.
    IF NOT EXISTS (SELECT 1 FROM tasks t WHERE t.id = revision.created_by_task AND t.type = 'research_cell') THEN
        RETURN NULL;
    END IF;
    SELECT array_agg(r.id ORDER BY r.id), array_agg(DISTINCT r.created_by_run), min(i.city_id)
    INTO batch, writers, city
    FROM revisions r JOIN items i ON i.current_revision = r.id
    WHERE r.created_by_task = revision.created_by_task AND i.state = 'checking'
      AND i.type IN ('story', 'guide', 'trail')
      AND NOT EXISTS (SELECT 1 FROM tasks t WHERE t.type = 'review' AND t.state IN ('queued', 'leased')
                      AND t.input -> 'revisions' ? r.id);
    IF EXISTS (SELECT 1 FROM unnest(batch) AS b(id) WHERE (evaluate(b.id) ->> 'missing') IS DISTINCT FROM 'review') THEN
        RETURN NULL;  -- some item in the submission still waits for its tool check
    END IF;
    RETURN enqueue(p_run, 'review', 'review:' || coalesce(revision.created_by_task, p_revision) || ':' ||
                   floor(extract(epoch FROM clock_timestamp()) * 1000),
                   jsonb_build_object('revisions', to_jsonb(batch)), city, NULL, NULL, NULL, writers, NULL, 10);
END;
$$;

CREATE FUNCTION plan_reviews(p_token text) RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['system']);
    size integer := setting('review.max_batch')::text::integer;
    waiting record;
    planned integer := 0;
BEGIN
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

-- Single-item reviews queued before this change are planned again in batches.
UPDATE tasks t SET state = 'cancelled', problem = 'replanned into a batch'
WHERE t.type = 'review' AND t.state = 'queued'
  AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements_text(t.input -> 'revisions') v(id)
                  JOIN revisions r ON r.id = v.id JOIN tasks w ON w.id = r.created_by_task
                  WHERE w.type = 'research_cell');

GRANT EXECUTE ON FUNCTION plan_reviews(text) TO psst_platform_system;
