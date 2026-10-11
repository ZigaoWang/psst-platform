-- Photos from Wikidata in code (decision 46): a place's own image (P18), free and credited on Commons, is queued
-- by the system with no model choosing it, imported like any chosen photo, and accepted on its tool check.
SET search_path = psst, public;

CREATE FUNCTION queue_wikidata_photo(p_token text, p_place text, p_choice jsonb) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    system runs := run_for(p_token, ARRAY['system']);
    place places;
BEGIN
    SELECT * INTO place FROM places WHERE id = p_place;
    IF NOT FOUND OR coalesce(p_choice ->> 'key', '') !~ '^commons:File:.+' THEN
        RAISE EXCEPTION 'a Wikidata photo is a place and a Commons key' USING ERRCODE = '22023';
    END IF;
    IF EXISTS (SELECT 1 FROM items WHERE place_id = p_place AND type = 'photo' AND state <> 'retired')
       OR EXISTS (SELECT 1 FROM tasks WHERE place_id = p_place AND type IN ('find_photos', 'import_photo')
                  AND state IN ('queued', 'leased')) THEN
        RETURN false;
    END IF;
    PERFORM enqueue(system.id, 'import_photo', 'import_photo:' || p_place || ':' || (p_choice ->> 'key'),
                    p_choice || jsonb_build_object('chosen_by', system.id, 'from', 'wikidata'),
                    place.city_id, p_place, NULL, NULL, '{}', NULL, 15);
    RETURN true;
END;
$$;

CREATE OR REPLACE FUNCTION create_photo(p_token text, p_task text, p_body jsonb, p_rulebook text) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    system runs := run_for(p_token, ARRAY['system']);
    task tasks := held_task(system, p_task);
    revision_id text;
BEGIN
    revision_id := create_revision(task.input ->> 'chosen_by', task.id, NULL, 'photo', task.place_id, task.city_id,
                                   NULL, NULL, 'en', p_body, '[]', p_rulebook,
                                   CASE WHEN task.input ->> 'from' = 'wikidata' THEN 'the place''s own Wikidata image'
                                        ELSE 'chosen from Commons' END);
    PERFORM advance(system.id, revision_id);
    RETURN revision_id;
END;
$$;

CREATE OR REPLACE FUNCTION evaluate(p_revision text) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    revision revisions;
    item items;
    since timestamptz;
    tool checks;
    verdict checks;
    source_item items;
BEGIN
    SELECT * INTO revision FROM revisions WHERE id = p_revision;
    SELECT * INTO item FROM items WHERE id = revision.item_id;
    IF item.state <> 'checking' OR item.current_revision <> p_revision THEN
        RETURN jsonb_build_object('outcome', 'none', 'reason', 'not being checked');
    END IF;
    since := item.checking_since;

    SELECT * INTO tool FROM checks WHERE revision_id = p_revision AND kind = 'tool' AND created_at >= since
    ORDER BY id DESC LIMIT 1;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('outcome', 'wait', 'missing', 'tool');
    ELSIF tool.verdict = 'fail' THEN
        RETURN jsonb_build_object('outcome', 'revise', 'problems', jsonb_build_array(tool.note), 'details', tool.details);
    END IF;

    IF item.type = 'translation' THEN
        SELECT * INTO source_item FROM items WHERE id = item.translates;
        IF revision.translation_of NOT IN (coalesce(source_item.published_revision, ''), coalesce(source_item.current_revision, ''))
           OR source_item.state NOT IN ('accepted', 'published', 'checking') THEN
            RETURN jsonb_build_object('outcome', 'revise', 'problems',
                                      jsonb_build_array('the text it translates has changed'));
        END IF;
    END IF;

    SELECT * INTO verdict FROM checks
    WHERE revision_id = p_revision AND claim_id IS NULL AND kind = 'editor' AND created_at >= since
    ORDER BY id DESC LIMIT 1;
    IF FOUND THEN
        RETURN CASE WHEN verdict.verdict = 'pass' THEN jsonb_build_object('outcome', 'accept')
                    ELSE jsonb_build_object('outcome', 'reject', 'problems', jsonb_build_array(verdict.note),
                                            'revisable', true) END;
    END IF;

    -- A place's own Wikidata image, its license and author read from Commons, needs no model to say it shows the
    -- place (decision 46): its tool check is enough.
    IF item.type = 'photo' AND revision.reason = 'the place''s own Wikidata image' THEN
        RETURN jsonb_build_object('outcome', 'accept');
    END IF;

    IF item.type IN ('translation', 'photo') THEN
        SELECT * INTO verdict FROM checks
        WHERE revision_id = p_revision AND claim_id IS NULL AND kind IN ('translation', 'item') AND created_at >= since
        ORDER BY id DESC LIMIT 1;
        IF NOT FOUND THEN
            RETURN jsonb_build_object('outcome', 'wait', 'missing', 'check');
        END IF;
        RETURN CASE WHEN verdict.verdict = 'pass' THEN jsonb_build_object('outcome', 'accept')
                    ELSE jsonb_build_object('outcome', 'revise', 'problems', jsonb_build_array(verdict.note)) END;
    END IF;

    SELECT * INTO verdict FROM checks
    WHERE revision_id = p_revision AND claim_id IS NULL AND kind = 'review' AND created_at >= since
    ORDER BY id DESC LIMIT 1;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('outcome', 'wait', 'missing', 'review');
    ELSIF verdict.verdict = 'pass' THEN
        RETURN jsonb_build_object('outcome', 'accept');
    END IF;
    RETURN jsonb_build_object('outcome', 'reject', 'problems', jsonb_build_array(verdict.note),
                              'revisable', coalesce((verdict.details ->> 'revisable')::boolean, false));
END;
$$;

GRANT EXECUTE ON FUNCTION queue_wikidata_photo(text, text, jsonb) TO psst_platform_system;
