-- Revisions go on while each round fixes what review named (decision 45). Code cuts never count. A revision a model
-- made is retired with the reason when its review says it repeats a problem it was asked to fix, or names a detail
-- no claim states that the revision added. A new review standard reopens what a review retired.
SET search_path = psst, public;

INSERT INTO lifecycle_moves VALUES ('retired', 'checking');

-- What the review said of one revision: its decision in the review task's result, or null for a review carried over
-- or recorded without one.
CREATE FUNCTION review_decision(p_revision text) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
    SELECT d FROM checks k JOIN tasks t ON t.id = k.task_id, jsonb_array_elements(t.result -> 'decisions') d
    WHERE k.revision_id = p_revision AND k.kind = 'review' AND k.claim_id IS NULL AND d ->> 'revision' = p_revision
    ORDER BY k.id DESC LIMIT 1
$$;

-- A revision made in code (a cut, a quote attached) says so in its reason.
CREATE FUNCTION made_in_code(p_revision text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
    SELECT coalesce(reason LIKE 'Made in code:%', false) FROM revisions WHERE id = p_revision
$$;

CREATE OR REPLACE FUNCTION send_back(p_run text, p_task text, p_revision text, p_problems jsonb, p_revisable boolean,
                                     p_exclude text[]) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    item items := (SELECT i FROM items i JOIN revisions r ON r.item_id = i.id WHERE r.id = p_revision);
    current revisions := (SELECT r FROM revisions r WHERE r.id = p_revision);
    reason text := (SELECT string_agg(value, '; ') FROM jsonb_array_elements_text(p_problems));
    decision jsonb := review_decision(p_revision);
    asked tasks;
    earlier revisions;
    added text;
BEGIN
    IF NOT p_revisable THEN
        PERFORM retire(p_run, item.id, 'rejected: ' || reason);
        RETURN 'retired';
    END IF;
    -- A model's revision of what a review named is held to it; a cut made in code is not a round.
    SELECT t.* INTO asked FROM tasks t
    WHERE t.id = current.created_by_task AND t.type = 'revise' AND t.input ? 'from_review';
    IF FOUND AND NOT made_in_code(p_revision) THEN
        IF coalesce((decision ->> 'repeated')::boolean, false) THEN
            PERFORM retire(p_run, item.id, 'rejected: the revision still has what it was asked to fix: ' || reason);
            RETURN 'retired';
        END IF;
        SELECT * INTO earlier FROM revisions WHERE id = asked.revision_id;
        SELECT string_agg(u, '; ') INTO added
        FROM jsonb_array_elements_text(coalesce(decision -> 'unclaimed', '[]')) u
        WHERE strpos(lower(current.body::text), lower(u)) > 0 AND strpos(lower(earlier.body::text), lower(u)) = 0;
        IF added IS NOT NULL THEN
            PERFORM retire(p_run, item.id, 'rejected: the revision added what no claim states: ' || added);
            RETURN 'retired';
        END IF;
    END IF;
    IF item.state <> 'draft' THEN
        PERFORM transition(item.id, 'draft', p_run, p_task, 'sent back: ' || reason);
    END IF;
    PERFORM enqueue(p_run, 'revise', 'revise:' || p_revision,
                    jsonb_build_object('problems', p_problems, 'from_review', true,
                                       'unclaimed', coalesce(decision -> 'unclaimed', '[]')),
                    item.city_id, item.place_id, item.id, p_revision, p_exclude, NULL, 8);
    RETURN 'revise';
END;
$$;

-- Accepted work, and work a review retired that a revision could still fix, goes back to review.
CREATE OR REPLACE FUNCTION review_again(p_token text, p_item text, p_reason text) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    system runs := run_for(p_token, ARRAY['system']);
    item items;
BEGIN
    IF coalesce(trim(p_reason), '') = '' THEN
        RAISE EXCEPTION 'say why the item is reviewed again' USING ERRCODE = '22023';
    END IF;
    SELECT * INTO item FROM items WHERE id = p_item FOR UPDATE;
    IF item.type IN ('story', 'guide') AND (item.state = 'accepted' OR (item.state = 'retired' AND EXISTS (
            SELECT 1 FROM (SELECT k.details FROM checks k WHERE k.revision_id = item.current_revision
                           AND k.kind = 'review' AND k.claim_id IS NULL ORDER BY k.id DESC LIMIT 1) last
            WHERE (last.details ->> 'revisable')::boolean))) THEN
        PERFORM transition(p_item, 'checking', system.id, NULL, p_reason);
        PERFORM advance(system.id, item.current_revision);
    END IF;
    RETURN (SELECT state FROM items WHERE id = p_item);
END;
$$;

GRANT EXECUTE ON FUNCTION review_decision(text), made_in_code(text) TO psst_platform_worker, psst_platform_system;
