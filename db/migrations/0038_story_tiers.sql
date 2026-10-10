-- Stories come in two tiers (decision 27): a featured story clears the "wait, really?" bar and leads the feed; a map
-- story is as true, specific, sourced, and visible, with a smaller surprise. The reviewer sets the tier of every good
-- story, and calibration measures the tier as well as the mark.
SET search_path = psst, public;

ALTER TABLE items ADD COLUMN tier text CHECK (tier IN ('featured', 'map'));
UPDATE items SET tier = 'featured' WHERE type = 'story' AND state IN ('accepted', 'published');
ALTER TABLE golden_stories ADD COLUMN tier text CHECK (tier IN ('featured', 'map'));
UPDATE golden_stories SET tier = 'featured' WHERE mark = 'good';
ALTER TABLE golden_stories ADD CONSTRAINT golden_stories_tier_needs_good CHECK ((mark = 'good') = (tier IS NOT NULL));

CREATE OR REPLACE FUNCTION golden_version() RETURNS text
LANGUAGE sql STABLE SET search_path = psst, public, pg_temp AS $$
    SELECT left(md5(coalesce(string_agg(id || ':' || mark || ':' || coalesce(tier, ''), ',' ORDER BY id), '')), 12) FROM golden_stories
$$;

CREATE OR REPLACE FUNCTION submit_task(p_token text, p_task text, p_result jsonb, p_prompt text DEFAULT NULL) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['worker', 'system']);
    task tasks := held_task(run, p_task);
    item items;
    claim_ids text[];
    entry record;
    decision jsonb;
    new_revision text;
    decided text[] := '{}';
    outcome jsonb := '{}';
    next jsonb := '{}';
BEGIN
    SELECT * INTO item FROM items WHERE id = task.item_id;
    CASE task.type
    WHEN 'audit' THEN
        claim_ids := ARRAY(SELECT id FROM claims WHERE revision_id = task.revision_id ORDER BY n);
        FOR entry IN SELECT * FROM verdicts_for(p_result, claim_ids) LOOP
            PERFORM record_check(run.id, task.id, task.revision_id, entry.id, 'audit', entry.verdict, entry.note);
        END LOOP;
        PERFORM record_check(run.id, task.id, task.revision_id, NULL, 'audit', p_result #>> '{item,verdict}',
                             p_result #>> '{item,note}', coalesce(p_result -> 'item', '{}'));
    WHEN 'review' THEN
        FOR decision IN SELECT value FROM jsonb_array_elements(coalesce(p_result -> 'decisions', '[]')) LOOP
            IF NOT task.input -> 'revisions' ? (decision ->> 'revision') THEN
                RAISE EXCEPTION 'revision % isn''t in this review', decision ->> 'revision' USING ERRCODE = '22023';
            END IF;
            decided := decided || (decision ->> 'revision');
        END LOOP;
        IF EXISTS (SELECT 1 FROM jsonb_array_elements_text(task.input -> 'revisions') AS r(id)
                   JOIN items i ON i.current_revision = r.id
                   WHERE i.state = 'checking' AND NOT r.id = ANY(decided)) THEN
            RAISE EXCEPTION 'decide every item in the review' USING ERRCODE = '22023';
        END IF;
    WHEN 'check_photo', 'check_translation' THEN
        IF p_result ->> 'verdict' = 'pass' AND jsonb_array_length(coalesce(p_result -> 'untraced', '[]')) > 0 THEN
            RAISE EXCEPTION 'details no claim states fail the check' USING ERRCODE = '22023';
        END IF;
        PERFORM record_check(run.id, task.id, task.revision_id, NULL,
                             CASE WHEN task.type = 'check_translation' THEN 'translation' ELSE 'item' END,
                             p_result ->> 'verdict', p_result ->> 'note', p_result);
    WHEN 'write_trail', 'revise', 'translate' THEN
        new_revision := create_revision(
            run.id, task.id,
            CASE WHEN task.type = 'revise' THEN task.item_id
                 WHEN task.type = 'translate' THEN (SELECT id FROM items WHERE translates = task.item_id
                                                     AND language = p_result ->> 'language' AND state <> 'retired')
            END,
            CASE task.type WHEN 'write_trail' THEN 'trail' WHEN 'translate' THEN 'translation' ELSE item.type END,
            task.place_id, task.city_id,
            CASE WHEN task.type = 'translate' THEN task.item_id END,
            CASE WHEN task.type = 'translate' THEN task.revision_id
                 WHEN task.type = 'revise' AND item.type = 'translation' THEN p_result ->> 'translation_of' END,
            coalesce(p_result ->> 'language', 'en'), p_result -> 'body', coalesce(p_result -> 'claims', '[]'),
            p_result ->> 'rulebook', coalesce(nullif(p_result ->> 'reason', ''), task.type), p_result ->> 'bar');
        outcome := jsonb_build_object('revision', new_revision);
    WHEN 'tool_check' THEN
        IF NOT EXISTS (SELECT 1 FROM checks c WHERE c.task_id = task.id AND c.kind = 'tool') THEN
            RAISE EXCEPTION 'record the tool check before submitting the task' USING ERRCODE = '22023';
        END IF;
    ELSE
        RAISE EXCEPTION 'task type % is submitted through its own command', task.type USING ERRCODE = '22023';
    END CASE;

    UPDATE tasks SET state = 'done', result = p_result, prompt = p_prompt, done_by = run.id, done_at = now(),
                     leased_by = NULL, leased_until = NULL
    WHERE id = task.id;

    IF task.type = 'audit' THEN
        outcome := outcome || jsonb_build_object('audit', settle_audit(run.id, (task.input ->> 'batch')));
    ELSIF task.type = 'review' THEN
        FOR decision IN SELECT value FROM jsonb_array_elements(p_result -> 'decisions') LOOP
            SELECT i.* INTO item FROM items i WHERE i.current_revision = decision ->> 'revision';
            IF NOT FOUND OR item.state <> 'checking' THEN
                CONTINUE;  -- retired meanwhile (its place was refused, for one)
            END IF;
            -- Good publishes, or first gets its one revision making the cut it names; weak gets its one revision
            -- aimed at the reason; bad is dropped.
            PERFORM record_check(run.id, task.id, decision ->> 'revision', NULL, 'review',
                                 CASE WHEN decision ->> 'mark' = 'good' AND decision ->> 'fix' IS NULL
                                      THEN 'pass' ELSE 'fail' END,
                                 coalesce(decision ->> 'fix', decision ->> 'reason'),
                                 jsonb_build_object('mark', decision ->> 'mark', 'reason', decision ->> 'reason',
                                                    'tier', decision ->> 'tier',
                                                    'revisable', decision ->> 'mark' <> 'bad'));
            -- The reviewer sets a good story's tier: featured leads the feed, a map story fills the map.
            IF decision ->> 'mark' = 'good' AND decision ->> 'tier' IS NOT NULL THEN
                UPDATE items SET tier = decision ->> 'tier' WHERE id = item.id;
            END IF;
            next := next || jsonb_build_object(decision ->> 'revision', advance(run.id, decision ->> 'revision'));
        END LOOP;
        PERFORM plan_review_audit(run.id, task.id);
        outcome := jsonb_build_object('decided', next);
    ELSE
        outcome := outcome || jsonb_build_object('next', advance(run.id, coalesce(new_revision, task.revision_id)));
    END IF;
    RETURN outcome;
END;
$$;

CREATE OR REPLACE FUNCTION submit_calibration(p_token text, p_task text, p_result jsonb, p_prompt text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['worker']);
    task tasks := held_task(run, p_task);
    fold integer := (task.input ->> 'fold')::integer;
    details jsonb;
    marked integer;
    agreed integer;
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
           count(*), count(*) FILTER (WHERE g.mark = m ->> 'mark'
                                        AND (g.mark <> 'good' OR g.tier IS NOT DISTINCT FROM m ->> 'tier'))
    INTO details, marked, agreed
    FROM golden_stories g JOIN jsonb_array_elements(p_result -> 'marks') m ON m ->> 'golden' = g.id
    WHERE golden_fold(g.id) = fold;
    INSERT INTO calibrations (task_id, run_id, model, prompt_version, bar_version, golden_version, fold, marked,
                              agreed, details)
    VALUES (task.id, run.id, run.model, task.input ->> 'prompt_version', task.input ->> 'bar_version',
            task.input ->> 'golden_version', fold, marked, agreed, details);
    UPDATE tasks SET state = 'done', result = p_result, prompt = p_prompt, done_by = run.id, done_at = now(),
                     leased_by = NULL, leased_until = NULL
    WHERE id = task.id;
    RETURN jsonb_build_object('fold', fold, 'marked', marked, 'agreed', agreed);
END;
$$;

DROP FUNCTION console_mark_story(text, text, text, text);
CREATE FUNCTION console_mark_story(p_token text, p_item text, p_mark text, p_reason text, p_tier text)
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
    INSERT INTO golden_stories (id, city_id, place, headline, short, long, sources, mark, tier, reason, item_id,
                                origin, marked_by)
    VALUES (golden_id, item.city_id,
            (SELECT name FROM place_names WHERE place_id = item.place_id AND role = 'display'),
            body ->> 'headline', body ->> 'short', (body ->> 'long') || ' ' || coalesce(body ->> 'look', ''),
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

GRANT EXECUTE ON FUNCTION console_mark_story(text, text, text, text, text) TO psst_platform_console;
SELECT apply_read_grants();
