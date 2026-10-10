-- Constructed negatives (decision 31): good golden stories broken in one known way each, so the gate measures
-- whether the reviewer catches defects as well as whether it publishes what the editor publishes. Every calibration
-- item shows its claims, the sentences of the unbroken story, as a review shows claims beside the prose. The gate
-- needs both bars: 90 percent of the editor's good stories published and 90 percent of the defects caught.
SET search_path = psst, public;

ALTER TABLE golden_stories ADD COLUMN defect text, ADD COLUMN claims jsonb, ADD COLUMN constructed_from text
    REFERENCES golden_stories;
ALTER TABLE golden_stories ADD CONSTRAINT golden_constructed_check
    CHECK ((defect IS NULL) = (constructed_from IS NULL) AND (defect IS NULL OR mark = 'weak'));
ALTER TABLE calibrations ADD COLUMN pos_marked integer, ADD COLUMN pos_agreed integer, ADD COLUMN neg_marked integer,
    ADD COLUMN neg_caught integer;

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
                                        'fix', m ->> 'fix',
                                        'reason', m ->> 'reason')),
           count(*), count(*) FILTER (WHERE (g.mark = 'good') = (m ->> 'mark' = 'good')),
           count(*) FILTER (WHERE g.mark = 'good' AND m ->> 'mark' = 'good'),
           count(*) FILTER (WHERE g.mark = 'good' AND m ->> 'mark' = 'good' AND g.tier = m ->> 'tier'),
           count(*) FILTER (WHERE g.mark = 'good'),
           count(*) FILTER (WHERE g.mark = 'good' AND m ->> 'mark' = 'good'),
           count(*) FILTER (WHERE g.mark <> 'good'),
           -- A defect is caught when the item is held back, or, for a constructed one, when a cut or fix is named.
           count(*) FILTER (WHERE g.mark <> 'good' AND (m ->> 'mark' <> 'good'
                                 OR (g.defect IS NOT NULL AND coalesce(m ->> 'fix', '') <> '')))
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

CREATE OR REPLACE FUNCTION gate_status(p_prompt text, p_bar text) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    routed text := task_model('review', '{}');
    golden text := golden_version();
    pos_marked integer := 0;
    pos_agreed integer := 0;
    neg_marked integer := 0;
    neg_caught integer := 0;
    missing integer[] := '{}';
    latest calibrations;
BEGIN
    FOR f IN 0 .. 1 LOOP
        SELECT * INTO latest FROM calibrations c
        WHERE c.fold = f AND c.model = routed AND c.prompt_version = p_prompt
          AND c.bar_version IS NOT DISTINCT FROM p_bar AND c.golden_version = golden
          AND c.created_at > now() - make_interval(days => setting('gate.max_age_days')::text::integer)
        ORDER BY c.created_at DESC LIMIT 1;
        IF FOUND THEN
            pos_marked := pos_marked + coalesce(latest.pos_marked, 0);
            pos_agreed := pos_agreed + coalesce(latest.pos_agreed, 0);
            neg_marked := neg_marked + coalesce(latest.neg_marked, 0);
            neg_caught := neg_caught + coalesce(latest.neg_caught, 0);
        ELSE
            missing := missing || f;
        END IF;
    END LOOP;
    -- Two bars, each at the minimum: the stories the editor publishes are published, and the defects are caught.
    RETURN jsonb_build_object(
        'open', cardinality(missing) = 0 AND pos_marked > 0 AND neg_marked > 0
                AND pos_agreed::numeric / pos_marked >= setting('gate.min_agreement')::text::numeric
                AND neg_caught::numeric / neg_marked >= setting('gate.min_agreement')::text::numeric,
        'agreement', CASE WHEN pos_marked > 0 THEN round(pos_agreed::numeric / pos_marked, 4) END,
        'caught', CASE WHEN neg_marked > 0 THEN round(neg_caught::numeric / neg_marked, 4) END,
        'missing_folds', to_jsonb(missing), 'model', routed, 'prompt_version', p_prompt, 'bar_version', p_bar,
        'golden_version', golden);
END;
$$;

-- Replacing the constructed negatives is the system's job (the command that builds them); the editor's own marks are
-- never touched.
CREATE FUNCTION replace_constructed_negatives(p_token text, p_rows jsonb) RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['system']);
BEGIN
    DELETE FROM golden_stories WHERE constructed_from IS NOT NULL;
    UPDATE golden_stories g SET claims = x -> 'claims' FROM jsonb_array_elements(p_rows) x
    WHERE x ->> 'claims_for' = g.id;
    INSERT INTO golden_stories (id, city_id, place, headline, short, long, look, sources, mark, tier, reason, origin,
                                marked_by, defect, claims, constructed_from)
    SELECT new_id('gs'), g.city_id, g.place, x ->> 'headline', x ->> 'short', x ->> 'long', x ->> 'look', g.sources,
           'weak', NULL, x ->> 'reason', 'constructed by ' || run.id, 'constructed', x ->> 'defect', g.claims, g.id
    FROM jsonb_array_elements(p_rows) x JOIN golden_stories g ON g.id = x ->> 'from'
    WHERE x ? 'from';
    RETURN (SELECT count(*) FROM golden_stories WHERE constructed_from IS NOT NULL);
END;
$$;

GRANT EXECUTE ON FUNCTION replace_constructed_negatives(text, jsonb) TO psst_platform_system;
SELECT apply_read_grants();
