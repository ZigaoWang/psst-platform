-- Reader intake (design.md, sections 5.6 and 6): problem reports and empty-area demand signals from the app and the
-- website. Anyone can send them, so a report never changes content: it is recorded, and the first open report on a
-- published item sends it back to checking while the published revision stays live.
SET search_path = psst, public;

-- The run every report is recorded under. It has no usable token; only these functions act for it.
INSERT INTO runs (id, kind, operator, token_hash, notes)
VALUES (new_id('ru'), 'system', 'reader intake', gen_random_bytes(32), 'problem reports and demand from readers');
INSERT INTO settings (key, value, note)
SELECT 'intake.run', to_jsonb(id), 'The run reader reports are recorded under.' FROM runs WHERE operator = 'reader intake';

CREATE FUNCTION submit_report(p_item text, p_reason text, p_message text, p_app_version text) RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run text := setting('intake.run') #>> '{}';
    item items;
BEGIN
    SELECT * INTO item FROM items WHERE id = p_item FOR UPDATE;
    IF NOT FOUND OR item.published_revision IS NULL OR item.state = 'retired' THEN
        RAISE EXCEPTION 'unknown item' USING ERRCODE = 'P0002';
    END IF;
    INSERT INTO reports (item_id, reason, message, app_version)
    VALUES (p_item, p_reason, nullif(left(btrim(coalesce(p_message, '')), 1000), ''), left(p_app_version, 40));
    IF item.state = 'published' THEN
        PERFORM transition(p_item, 'checking', run, NULL, 'a reader reported it as ' || p_reason);
        PERFORM advance(run, item.current_revision);
    END IF;
END;
$$;

CREATE FUNCTION record_demand(p_cell text) RETURNS void
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
    INSERT INTO demand (cell, day, count) VALUES (p_cell, current_date, 1)
    ON CONFLICT (cell, day) DO UPDATE SET count = demand.count + 1
$$;

GRANT EXECUTE ON FUNCTION submit_report(text, text, text, text), record_demand(text) TO psst_platform_api;

-- An item's open reports are resolved when it is next published (after its checks) or retired.
CREATE FUNCTION resolve_reports() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = psst, pg_temp AS $$
BEGIN
    UPDATE reports SET state = 'resolved', resolved_at = now(), resolved_by = NEW.run_id,
                       resolution = CASE NEW.to_state WHEN 'published' THEN 'checked again and published'
                                                      ELSE 'retired: ' || NEW.reason END
    WHERE item_id = NEW.item_id AND state = 'open';
    RETURN NULL;
END;
$$;
CREATE TRIGGER transitions_resolve_reports AFTER INSERT ON transitions
    FOR EACH ROW WHEN (NEW.to_state IN ('published', 'retired')) EXECUTE FUNCTION resolve_reports();

-- settle_publication, now also returning to published an item that was checked again and passed with the revision
-- already live (after a report or an editor's recheck).
CREATE OR REPLACE FUNCTION settle_publication(p_token text, p_publication text, p_promoted boolean, p_checks jsonb)
RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['publisher']);
    publication publications;
    entry record;
    went_live integer := 0;
BEGIN
    SELECT * INTO publication FROM publications WHERE id = p_publication FOR UPDATE;
    IF publication.state <> 'staged' THEN
        RAISE EXCEPTION 'publication % is already %', p_publication, publication.state USING ERRCODE = 'P0001';
    END IF;
    UPDATE publications SET state = CASE WHEN p_promoted THEN 'promoted' ELSE 'failed' END, checks = p_checks,
                            settled_at = now()
    WHERE id = p_publication;
    IF NOT p_promoted THEN
        RETURN 0;
    END IF;
    FOR entry IN
        SELECT i.id, p.revision_id FROM publication_items p JOIN items i ON i.id = p.item_id
        WHERE p.publication_id = p_publication AND i.state = 'accepted' AND i.current_revision = p.revision_id
    LOOP
        UPDATE items SET published_revision = entry.revision_id WHERE id = entry.id;
        PERFORM transition(entry.id, 'published', run.id, NULL, 'published in ' || publication.content_version);
        went_live := went_live + 1;
    END LOOP;
    RETURN went_live;
END;
$$;
