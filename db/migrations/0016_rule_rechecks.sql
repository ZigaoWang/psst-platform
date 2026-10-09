-- Rechecking content after a rulebook change (design.md, section 9): an accepted or published item whose last tool
-- check ran under an older rulebook goes back to checking (a published one stays live meanwhile).
SET search_path = psst, public;

CREATE FUNCTION recheck_for_rules(p_token text, p_item text, p_rulebook text) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    system runs := run_for(p_token, ARRAY['system']);
    item items;
BEGIN
    SELECT * INTO item FROM items WHERE id = p_item FOR UPDATE;
    IF item.state IN ('accepted', 'published') THEN
        PERFORM transition(p_item, 'checking', system.id, NULL, 'the rulebook changed to ' || p_rulebook);
        PERFORM advance(system.id, item.current_revision);
    END IF;
    RETURN (SELECT state FROM items WHERE id = p_item);
END;
$$;

GRANT EXECUTE ON FUNCTION recheck_for_rules(text, text, text) TO psst_platform_system;

-- record_tool_check, now advancing the revision once the verdict is recorded, so a tool check run outside a task (a
-- recheck after a rule change) settles the revision the same way.
CREATE OR REPLACE FUNCTION record_tool_check(p_token text, p_task text, p_revision text, p_pass boolean, p_note text,
                                             p_details jsonb, p_matches jsonb) RETURNS bigint
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    system runs := run_for(p_token, ARRAY['system']);
    hit jsonb;
    check_id bigint;
BEGIN
    FOR hit IN SELECT value FROM jsonb_array_elements(coalesce(p_matches, '[]')) LOOP
        UPDATE evidence e
        SET matched = (hit ->> 'start') IS NOT NULL,
            quote_start = (hit ->> 'start')::integer,
            quote_end = (hit ->> 'end')::integer
        FROM claims c
        WHERE e.id = (hit ->> 'evidence')::bigint AND c.id = e.claim_id AND c.revision_id = p_revision
          AND e.matched IS NULL;
    END LOOP;
    check_id := record_check(system.id, p_task, p_revision, NULL, 'tool', CASE WHEN p_pass THEN 'pass' ELSE 'fail' END,
                             p_note, p_details);
    PERFORM advance(system.id, p_revision);
    RETURN check_id;
END;
$$;

-- transition, no longer cancelling a task held by the run making the change (the tool check whose failing verdict
-- sends the revision back is still the system worker's to close).
CREATE OR REPLACE FUNCTION transition(p_item text, p_to text, p_run text, p_task text, p_reason text) RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    item items;
BEGIN
    SELECT * INTO item FROM items WHERE id = p_item FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'unknown item %', p_item USING ERRCODE = 'P0002';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM lifecycle_moves WHERE from_state = item.state AND to_state = p_to) THEN
        RAISE EXCEPTION 'item % can''t move from % to %', p_item, item.state, p_to USING ERRCODE = 'P0001';
    END IF;
    PERFORM set_config('psst.in_transition', 'on', true);
    UPDATE items SET state = p_to,
                     checking_since = CASE WHEN p_to = 'checking' THEN now() ELSE checking_since END
    WHERE id = p_item;
    PERFORM set_config('psst.in_transition', 'off', true);
    INSERT INTO transitions (item_id, from_state, to_state, revision_id, run_id, task_id, reason)
    VALUES (p_item, item.state, p_to, item.current_revision, p_run, p_task, p_reason);
    IF item.state = 'checking' THEN
        UPDATE tasks SET state = 'cancelled', leased_by = NULL, leased_until = NULL,
                         problem = 'the revision is no longer being checked'
        WHERE item_id = p_item AND state IN ('queued', 'leased') AND id IS DISTINCT FROM p_task
          AND leased_by IS DISTINCT FROM p_run
          AND type IN ('tool_check', 'check_claims_a', 'check_claims_b', 'check_item', 'check_photo',
                       'check_translation', 'escalate');
    END IF;
END;
$$;
