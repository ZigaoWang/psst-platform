-- An audit checks an accepted revision. When an item leaves accepted (sent back, rechecked, retired, or published
-- with a new revision coming), its waiting audits are cancelled, instead of being leased, refused, and retried.
SET search_path = psst, public;

CREATE FUNCTION cancel_stale_audits() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
BEGIN
    UPDATE tasks SET state = 'cancelled', problem = 'its revision is no longer the accepted one'
    WHERE type = 'audit' AND state = 'queued' AND item_id = NEW.item_id;
    RETURN NEW;
END;
$$;

CREATE TRIGGER audits_follow_items AFTER INSERT ON transitions
FOR EACH ROW WHEN (NEW.from_state = 'accepted' AND NEW.to_state IN ('checking', 'draft', 'retired'))
EXECUTE FUNCTION cancel_stale_audits();
