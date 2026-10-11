-- Accepted work reviewed again after the review itself changes (decision 44): the item goes back to checking
-- without the review it passed, so the next review planning batches it under the current review prompt.
SET search_path = psst, public;

CREATE FUNCTION review_again(p_token text, p_item text, p_reason text) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    system runs := run_for(p_token, ARRAY['system']);
    item items;
BEGIN
    IF coalesce(trim(p_reason), '') = '' THEN
        RAISE EXCEPTION 'say why the item is reviewed again' USING ERRCODE = '22023';
    END IF;
    SELECT * INTO item FROM items WHERE id = p_item FOR UPDATE;
    IF item.state = 'accepted' AND item.type IN ('story', 'guide') THEN
        PERFORM transition(p_item, 'checking', system.id, NULL, p_reason);
        PERFORM advance(system.id, item.current_revision);
    END IF;
    RETURN (SELECT state FROM items WHERE id = p_item);
END;
$$;

GRANT EXECUTE ON FUNCTION review_again(text, text, text) TO psst_platform_system;
