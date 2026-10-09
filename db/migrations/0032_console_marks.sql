-- The editor marks published stories from the console (decision 25); each mark joins the golden set, so the next
-- calibration measures the reviewer against it. Nothing waits on these marks.
SET search_path = psst, public;

CREATE UNIQUE INDEX golden_stories_item_idx ON golden_stories (item_id) WHERE item_id IS NOT NULL;

CREATE FUNCTION console_mark_story(p_token text, p_item text, p_mark text, p_reason text) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run text := console_act(p_token, 'mark story', p_item, jsonb_build_object('mark', p_mark, 'reason', p_reason));
    item items;
    body jsonb;
    golden_id text := new_id('gs');
BEGIN
    IF p_mark NOT IN ('good', 'weak', 'bad') OR coalesce(btrim(p_reason), '') = '' THEN
        RAISE EXCEPTION 'mark it good, weak, or bad, and say why in a line' USING ERRCODE = '22023';
    END IF;
    SELECT * INTO item FROM items WHERE id = p_item;
    IF NOT FOUND OR item.type <> 'story' OR item.published_revision IS NULL THEN
        RAISE EXCEPTION 'only published stories are marked' USING ERRCODE = '22023';
    END IF;
    body := (SELECT r.body FROM revisions r WHERE r.id = item.published_revision);
    INSERT INTO golden_stories (id, city_id, place, headline, short, long, sources, mark, reason, item_id, origin,
                                marked_by)
    VALUES (golden_id, item.city_id,
            (SELECT name FROM place_names WHERE place_id = item.place_id AND role = 'display'),
            body ->> 'headline', body ->> 'short', (body ->> 'long') || ' ' || coalesce(body ->> 'look', ''),
            coalesce((SELECT string_agg(DISTINCT s.publisher, '; ') FROM claims c JOIN evidence e ON e.claim_id = c.id
                      JOIN snapshots n ON n.id = e.snapshot_id JOIN sources s ON s.id = n.source_id
                      WHERE c.revision_id = item.published_revision), 'none'),
            p_mark, btrim(p_reason), item.id, item.published_revision,
            'editor, console sample, ' || to_char(now(), 'YYYY-MM'))
    ON CONFLICT (item_id) WHERE item_id IS NOT NULL
    DO UPDATE SET mark = EXCLUDED.mark, reason = EXCLUDED.reason, marked_by = EXCLUDED.marked_by;
    RETURN golden_id;
END;
$$;

GRANT EXECUTE ON FUNCTION console_mark_story(text, text, text, text) TO psst_platform_console;
