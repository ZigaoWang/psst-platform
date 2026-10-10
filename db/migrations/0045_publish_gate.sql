-- The gate is the publish decision (decision 30): a calibration agrees with the editor when it publishes what the
-- editor would publish (good, featured or map) and holds back what the editor would hold back (weak or bad). Tier
-- agreement is recorded beside it and reported, not gated. Golden stories keep their look line apart, since what a
-- reader can see from where they stand decides a mark. Every quote the harness repairs is logged.
SET search_path = psst, public;

ALTER TABLE golden_stories ADD COLUMN look text;
ALTER TABLE calibrations ADD COLUMN tier_marked integer, ADD COLUMN tier_agreed integer;

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
                                        'editor_tier', g.tier, 'reviewer_tier', m ->> 'tier',
                                        'reason', m ->> 'reason')),
           count(*), count(*) FILTER (WHERE (g.mark = 'good') = (m ->> 'mark' = 'good')),
           count(*) FILTER (WHERE g.mark = 'good' AND m ->> 'mark' = 'good'),
           count(*) FILTER (WHERE g.mark = 'good' AND m ->> 'mark' = 'good' AND g.tier = m ->> 'tier')
    INTO details, marked, agreed, tier_marked, tier_agreed
    FROM golden_stories g JOIN jsonb_array_elements(p_result -> 'marks') m ON m ->> 'golden' = g.id
    WHERE golden_fold(g.id) = fold;
    INSERT INTO calibrations (task_id, run_id, model, prompt_version, bar_version, golden_version, fold, marked,
                              agreed, tier_marked, tier_agreed, details)
    VALUES (task.id, run.id, run.model, task.input ->> 'prompt_version', task.input ->> 'bar_version',
            task.input ->> 'golden_version', fold, marked, agreed, tier_marked, tier_agreed, details);
    UPDATE tasks SET state = 'done', result = p_result, prompt = p_prompt, done_by = run.id, done_at = now(),
                     leased_by = NULL, leased_until = NULL
    WHERE id = task.id;
    RETURN jsonb_build_object('fold', fold, 'marked', marked, 'agreed', agreed, 'tier_marked', tier_marked,
                              'tier_agreed', tier_agreed);
END;
$$;

CREATE OR REPLACE FUNCTION console_mark_story(p_token text, p_item text, p_mark text, p_reason text, p_tier text)
RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run text := console_act(p_token, 'mark story', p_item, jsonb_build_object('mark', p_mark, 'tier', p_tier, 'reason', p_reason));
    item items;
    body jsonb;
    golden_id text := new_id('gs');
BEGIN
    IF p_mark NOT IN ('good', 'weak', 'bad') OR coalesce(btrim(p_reason), '') = '' THEN
        RAISE EXCEPTION 'mark it good, weak, or bad, and say why in a line' USING ERRCODE = '22023';
    END IF;
    IF (p_mark = 'good') <> coalesce(p_tier IN ('featured', 'map'), false) OR (p_mark <> 'good' AND p_tier IS NOT NULL) THEN
        RAISE EXCEPTION 'a good story is featured or map; weak and bad have no tier' USING ERRCODE = '22023';
    END IF;
    SELECT * INTO item FROM items WHERE id = p_item;
    IF NOT FOUND OR item.type <> 'story' OR item.published_revision IS NULL THEN
        RAISE EXCEPTION 'only published stories are marked' USING ERRCODE = '22023';
    END IF;
    body := (SELECT r.body FROM revisions r WHERE r.id = item.published_revision);
    INSERT INTO golden_stories (id, city_id, place, headline, short, long, look, sources, mark, tier, reason,
                                item_id, origin, marked_by)
    VALUES (golden_id, item.city_id,
            (SELECT name FROM place_names WHERE place_id = item.place_id AND role = 'display'),
            body ->> 'headline', body ->> 'short', body ->> 'long', body ->> 'look',
            coalesce((SELECT string_agg(DISTINCT s.publisher, '; ') FROM claims c JOIN evidence e ON e.claim_id = c.id
                      JOIN snapshots n ON n.id = e.snapshot_id JOIN sources s ON s.id = n.source_id
                      WHERE c.revision_id = item.published_revision), 'none'),
            p_mark, p_tier, btrim(p_reason), item.id, item.published_revision,
            'editor, console sample, ' || to_char(now(), 'YYYY-MM'))
    ON CONFLICT (item_id) WHERE item_id IS NOT NULL
    DO UPDATE SET mark = EXCLUDED.mark, tier = EXCLUDED.tier, reason = EXCLUDED.reason, marked_by = EXCLUDED.marked_by;
    RETURN golden_id;
END;
$$;

-- A quote the harness replaced with the snapshot's exact text, kept on the place it was written for, and shown to
-- the reviewer and the auditor beside the claim.
CREATE TABLE quote_repairs (
    id          bigserial PRIMARY KEY,
    task_id     text REFERENCES tasks,
    place_id    text REFERENCES places,
    model       text NOT NULL,
    snapshot_id text NOT NULL REFERENCES snapshots,
    written     text NOT NULL,
    exact       text NOT NULL,
    similarity  numeric(4, 3) NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX quote_repairs_place_idx ON quote_repairs (place_id);
ALTER TABLE harness_calls ADD COLUMN quotes jsonb;  -- per answer: quotes, exact, repaired, invented, unknown snapshot

CREATE FUNCTION record_quote_repairs(p_token text, p_task text, p_place text, p_model text, p_call bigint,
                                     p_stats jsonb, p_repairs jsonb) RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['worker']);
BEGIN
    UPDATE harness_calls SET quotes = p_stats WHERE id = p_call AND run_id = run.id;
    INSERT INTO quote_repairs (task_id, place_id, model, snapshot_id, written, exact, similarity)
    SELECT p_task, p_place, p_model, r ->> 'snapshot', r ->> 'written', r ->> 'exact', (r ->> 'similarity')::numeric
    FROM jsonb_array_elements(coalesce(p_repairs, '[]')) r;
END;
$$;

GRANT EXECUTE ON FUNCTION record_quote_repairs(text, text, text, text, bigint, jsonb, jsonb) TO psst_platform_worker;
SELECT apply_read_grants();
