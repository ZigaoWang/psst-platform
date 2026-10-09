-- The whole-item check runs first and the two claim checks only after it passes. It is one check instead of two
-- and fails more often, so a story sent back for an untraced detail no longer costs claim checks that are then
-- cancelled. Translations and photos have one check and are unchanged.
SET search_path = psst, public;

CREATE OR REPLACE FUNCTION advance(p_run text, p_revision text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    revision revisions;
    item items;
    result jsonb;
    round text;
    writer text[];
BEGIN
    SELECT * INTO revision FROM revisions WHERE id = p_revision;
    SELECT * INTO item FROM items WHERE id = revision.item_id FOR UPDATE;
    IF item.current_revision IS DISTINCT FROM p_revision OR item.state <> 'checking' THEN
        RETURN jsonb_build_object('outcome', 'none');
    END IF;
    round := p_revision || ':' || floor(extract(epoch FROM item.checking_since) * 1000)::bigint;
    writer := ARRAY[revision.created_by_run];
    result := evaluate(p_revision);
    CASE result ->> 'outcome'
    WHEN 'wait' THEN
        IF result ->> 'missing' = 'tool' THEN
            PERFORM enqueue(p_run, 'tool_check', 'tool_check:' || round, '{}', item.city_id, item.place_id, item.id,
                            p_revision);
        ELSIF item.type = 'translation' THEN
            PERFORM enqueue(p_run, 'check_translation', 'check_translation:' || round, '{}', item.city_id,
                            item.place_id, item.id, p_revision, writer, p_revision);
        ELSIF NOT EXISTS (SELECT 1 FROM checks WHERE revision_id = p_revision AND claim_id IS NULL
                          AND kind IN ('item', 'editor', 'escalation') AND created_at >= item.checking_since) THEN
            PERFORM enqueue(p_run, CASE WHEN item.type = 'photo' THEN 'check_photo' ELSE 'check_item' END,
                            'check_item:' || round, '{}', item.city_id, item.place_id, item.id, p_revision, writer,
                            p_revision);
        ELSIF EXISTS (SELECT 1 FROM claims WHERE revision_id = p_revision) THEN
            PERFORM enqueue(p_run, t, t || ':' || round, '{}', item.city_id, item.place_id, item.id, p_revision,
                            writer, p_revision)
            FROM unnest(ARRAY['check_claims_a', 'check_claims_b']) AS t;
        END IF;
    WHEN 'escalate' THEN
        PERFORM enqueue(p_run, 'escalate', 'escalate:' || round,
                        jsonb_build_object('claims', result -> 'claims', 'item', result -> 'item'),
                        item.city_id, item.place_id, item.id, p_revision, writer, p_revision, 10);
    WHEN 'accept', 'revise' THEN
        PERFORM settle(p_run, NULL, p_revision);
        IF result ->> 'outcome' = 'revise' THEN
            PERFORM enqueue(p_run, 'revise', 'revise:' || round, jsonb_build_object('problems', result -> 'problems'),
                            item.city_id, item.place_id, item.id, p_revision, '{}', NULL, 5);
        END IF;
    ELSE
        NULL;
    END CASE;
    RETURN result;
END;
$$;
