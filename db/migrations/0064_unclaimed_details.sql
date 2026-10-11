-- Review checks the prose against its claims, sentence by sentence: each mark lists the details the prose adds that
-- no claim states. The gate gains constructed negatives that add one such detail (a material, a feature, a judgment),
-- and counts one caught only when the reviewer names that detail, not for any fix at all.
SET search_path = psst, public;

ALTER TABLE golden_stories ADD COLUMN marker text;
ALTER TABLE golden_stories ADD CONSTRAINT golden_marker_check CHECK (marker IS NULL OR defect IS NOT NULL);

CREATE OR REPLACE FUNCTION submit_calibration(p_token text, p_task text, p_result jsonb, p_prompt text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['worker']);
    task tasks := held_task(run, p_task);
    fold integer := (task.input ->> 'fold')::integer;
    details jsonb;
    marked integer;
    agreed integer;
    tier_marked integer;
    tier_agreed integer;
    pos_marked integer;
    pos_agreed integer;
    neg_marked integer;
    neg_caught integer;
BEGIN
    IF task.type <> 'calibrate' THEN
        RAISE EXCEPTION 'task % is not a calibration', p_task USING ERRCODE = '22023';
    END IF;
    IF task.input ->> 'golden_version' IS DISTINCT FROM golden_version() THEN
        RAISE EXCEPTION 'the golden set changed since this calibration was queued' USING ERRCODE = 'P0001';
    END IF;
    IF EXISTS (SELECT 1 FROM golden_stories g WHERE golden_fold(g.id) = fold
               AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(p_result -> 'marks') m WHERE m ->> 'golden' = g.id)) THEN
        RAISE EXCEPTION 'mark every story in the fold' USING ERRCODE = '22023';
    END IF;
    SELECT jsonb_agg(jsonb_build_object('golden', g.id, 'editor', g.mark, 'reviewer', m ->> 'mark',
                                        'editor_tier', g.tier, 'reviewer_tier', m ->> 'tier', 'defect', g.defect,
                                        'fix', m ->> 'fix', 'unclaimed', m -> 'unclaimed', 'marker', g.marker,
                                        'reason', m ->> 'reason')),
           count(*), count(*) FILTER (WHERE (g.mark = 'good') = (m ->> 'mark' = 'good')),
           count(*) FILTER (WHERE g.mark = 'good' AND m ->> 'mark' = 'good'),
           count(*) FILTER (WHERE g.mark = 'good' AND m ->> 'mark' = 'good' AND g.tier = m ->> 'tier'),
           count(*) FILTER (WHERE g.mark = 'good'),
           count(*) FILTER (WHERE g.mark = 'good' AND m ->> 'mark' = 'good'),
           count(*) FILTER (WHERE g.mark <> 'good'),
           -- A defect is caught when the item is held back, or, for a constructed one, when a cut or fix is named.
           -- An added detail is caught only when the reviewer names it: its marker word in the fix or the
           -- details listed as unclaimed.
           count(*) FILTER (WHERE g.mark <> 'good' AND (m ->> 'mark' <> 'good'
                                 OR (g.defect IS NOT NULL AND coalesce(m ->> 'fix', '') <> ''
                                     AND (g.marker IS NULL
                                          OR (coalesce(m ->> 'fix', '') || ' ' || coalesce(m ->> 'unclaimed', ''))
                                             ILIKE '%' || g.marker || '%'))))
    INTO details, marked, agreed, tier_marked, tier_agreed, pos_marked, pos_agreed, neg_marked, neg_caught
    FROM golden_stories g JOIN jsonb_array_elements(p_result -> 'marks') m ON m ->> 'golden' = g.id
    WHERE golden_fold(g.id) = fold;
    INSERT INTO calibrations (task_id, run_id, model, prompt_version, bar_version, golden_version, fold, marked,
                              agreed, tier_marked, tier_agreed, pos_marked, pos_agreed, neg_marked, neg_caught, details)
    VALUES (task.id, run.id, run.model, task.input ->> 'prompt_version', task.input ->> 'bar_version',
            task.input ->> 'golden_version', fold, marked, agreed, tier_marked, tier_agreed, pos_marked, pos_agreed,
            neg_marked, neg_caught, details);
    UPDATE tasks SET state = 'done', result = p_result, prompt = p_prompt, done_by = run.id, done_at = now(),
                     leased_by = NULL, leased_until = NULL
    WHERE id = task.id;
    RETURN jsonb_build_object('fold', fold, 'published', pos_agreed || '/' || pos_marked,
                              'caught', neg_caught || '/' || neg_marked, 'tier', tier_agreed || '/' || tier_marked);
END;
$$;

CREATE OR REPLACE FUNCTION replace_constructed_negatives(p_token text, p_rows jsonb) RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['system']);
BEGIN
    DELETE FROM golden_stories WHERE constructed_from IS NOT NULL;
    UPDATE golden_stories g SET claims = x -> 'claims' FROM jsonb_array_elements(p_rows) x
    WHERE x ->> 'claims_for' = g.id;
    INSERT INTO golden_stories (id, city_id, place, headline, short, long, look, sources, mark, tier, reason, origin,
                                marked_by, defect, claims, constructed_from, marker)
    SELECT new_id('gs'), g.city_id, g.place, x ->> 'headline', x ->> 'short', x ->> 'long', x ->> 'look', g.sources,
           'weak', NULL, x ->> 'reason', 'constructed by ' || run.id, 'constructed', x ->> 'defect', g.claims, g.id, x ->> 'marker'
    FROM jsonb_array_elements(p_rows) x JOIN golden_stories g ON g.id = x ->> 'from'
    WHERE x ? 'from';
    RETURN (SELECT count(*) FROM golden_stories WHERE constructed_from IS NOT NULL);
END;
$$;
