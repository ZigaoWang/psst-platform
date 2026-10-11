-- A recheck after a rule change runs the tool checks again on the same revision; its prose hasn't changed, so the
-- review it passed stands (decision 43). Only a new revision, or an item an audit sends back, is reviewed again.
SET search_path = psst, public;

CREATE OR REPLACE FUNCTION recheck_for_rules(p_token text, p_item text, p_rulebook text) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    system runs := run_for(p_token, ARRAY['system']);
    item items;
    passed checks;
BEGIN
    SELECT * INTO item FROM items WHERE id = p_item FOR UPDATE;
    IF item.state IN ('accepted', 'published') THEN
        SELECT * INTO passed FROM checks
        WHERE revision_id = item.current_revision AND kind = 'review' AND claim_id IS NULL
        ORDER BY id DESC LIMIT 1;
        PERFORM transition(p_item, 'checking', system.id, NULL, 'the rulebook changed to ' || p_rulebook);
        IF FOUND AND passed.verdict = 'pass' THEN
            PERFORM record_check(passed.run_id, NULL, item.current_revision, NULL, 'review', 'pass',
                                 'the review this revision passed, kept through a recheck',
                                 passed.details || jsonb_build_object('kept_from', passed.id));
        END IF;
        PERFORM advance(system.id, item.current_revision);
    END IF;
    RETURN (SELECT state FROM items WHERE id = p_item);
END;
$$;
