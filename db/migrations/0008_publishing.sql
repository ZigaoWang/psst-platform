-- Publishing (design.md, section 11): what may publish, every staged and promoted output version, and marking
-- what went live.
SET search_path = psst, public;

-- The publisher starts its own kind of run.
ALTER TABLE runs DROP CONSTRAINT runs_kind_check;
ALTER TABLE runs ADD CONSTRAINT runs_kind_check CHECK (kind IN ('worker', 'editor', 'system', 'publisher'));

CREATE OR REPLACE FUNCTION caller_may_run(p_kind text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = psst, pg_temp AS $$
    SELECT session_user = (SELECT nspowner::regrole::text FROM pg_namespace WHERE nspname = 'psst')
        OR pg_has_role(session_user, CASE p_kind WHEN 'worker' THEN 'psst_platform_worker'
                                                 WHEN 'system' THEN 'psst_platform_system'
                                                 WHEN 'editor' THEN 'psst_platform_console'
                                                 WHEN 'publisher' THEN 'psst_platform_publisher' END, 'MEMBER')
$$;

-- The one definition of what the next publish contains: for every item that isn't retired, the revision to
-- publish. That is its accepted revision once the revision's audit batch has passed; otherwise the revision
-- already published, which stays live while a newer one is checked.
CREATE VIEW publishable AS
SELECT i.id AS item_id, i.type, i.place_id, i.city_id, i.translates, i.language, i.position,
       CASE WHEN audited.passed THEN i.current_revision ELSE i.published_revision END AS revision_id,
       coalesce(audited.passed, false) AND i.current_revision IS DISTINCT FROM i.published_revision AS is_new
FROM items i
LEFT JOIN LATERAL (
    SELECT true AS passed FROM audit_members m JOIN audit_batches b ON b.id = m.batch_id
    WHERE i.state = 'accepted' AND m.revision_id = i.current_revision AND b.outcome = 'passed' LIMIT 1
) audited ON true
WHERE i.state <> 'retired' AND (audited.passed OR i.published_revision IS NOT NULL);

-- Accepted work that can't publish yet, and why.
CREATE VIEW held_back AS
SELECT i.id AS item_id, i.type, i.place_id, i.city_id, i.current_revision AS revision_id,
       CASE WHEN EXISTS (SELECT 1 FROM audit_members m JOIN audit_batches b ON b.id = m.batch_id
                         WHERE m.revision_id = i.current_revision AND b.outcome = 'open')
            THEN 'its audit batch is still open'
            ELSE 'waiting to be audited' END AS reason
FROM items i
WHERE i.state = 'accepted' AND NOT EXISTS (
    SELECT 1 FROM audit_members m JOIN audit_batches b ON b.id = m.batch_id
    WHERE m.revision_id = i.current_revision AND b.outcome = 'passed');

CREATE TABLE publications (
    id              text PRIMARY KEY CHECK (id ~ id_pattern('pb')),
    content_version text NOT NULL UNIQUE CHECK (content_version ~ '^[0-9]{8}T[0-9]{6}Z$'),
    state           text NOT NULL DEFAULT 'staged' CHECK (state IN ('staged', 'promoted', 'failed', 'rolled_back')),
    manifest        jsonb NOT NULL,
    counts          jsonb NOT NULL,
    changes         jsonb NOT NULL DEFAULT '{}',
    held            jsonb NOT NULL DEFAULT '[]',
    checks          jsonb NOT NULL DEFAULT '[]',
    run_id          text NOT NULL REFERENCES runs,
    created_at      timestamptz NOT NULL DEFAULT now(),
    settled_at      timestamptz,
    notes           text
);
CREATE INDEX publications_created_idx ON publications (created_at DESC);

-- Exactly which revision of which item a publication contains, so the console can show diffs and promotion
-- marks exactly what went live.
CREATE TABLE publication_items (
    publication_id text NOT NULL REFERENCES publications,
    item_id        text NOT NULL REFERENCES items,
    revision_id    text NOT NULL REFERENCES revisions,
    PRIMARY KEY (publication_id, item_id)
);
CREATE INDEX publication_items_revision_idx ON publication_items (revision_id);

CREATE FUNCTION record_publication(p_token text, p_version text, p_manifest jsonb, p_counts jsonb, p_items jsonb,
                                   p_changes jsonb, p_held jsonb) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['publisher']);
    publication text := new_id('pb');
BEGIN
    INSERT INTO publications (id, content_version, manifest, counts, changes, held, run_id)
    VALUES (publication, p_version, p_manifest, p_counts, coalesce(p_changes, '{}'), coalesce(p_held, '[]'), run.id);
    INSERT INTO publication_items (publication_id, item_id, revision_id)
    SELECT publication, value ->> 'item', value ->> 'revision' FROM jsonb_array_elements(p_items);
    RETURN publication;
END;
$$;

-- Records the acceptance checks and, if they passed, that the publication is live: every new revision in it
-- becomes the item's published revision.
CREATE FUNCTION settle_publication(p_token text, p_publication text, p_promoted boolean, p_checks jsonb)
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
        SELECT i.id, i.state, i.current_revision, p.revision_id FROM publication_items p JOIN items i ON i.id = p.item_id
        WHERE p.publication_id = p_publication AND i.published_revision IS DISTINCT FROM p.revision_id
    LOOP
        IF entry.state = 'accepted' AND entry.current_revision = entry.revision_id THEN
            UPDATE items SET published_revision = entry.revision_id WHERE id = entry.id;
            PERFORM transition(entry.id, 'published', run.id, NULL, 'published in ' || publication.content_version);
            went_live := went_live + 1;
        END IF;
    END LOOP;
    RETURN went_live;
END;
$$;

-- Records that production was pointed back at an earlier publication. The database's published revisions are
-- not changed: the next publish builds from them again, after the problem is fixed or retired.
CREATE FUNCTION record_rollback(p_token text, p_from text, p_to text) RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['publisher']);
BEGIN
    UPDATE publications SET state = 'rolled_back', notes = format('rolled back to %s by %s', p_to, run.id)
    WHERE content_version = p_from AND state = 'promoted';
END;
$$;

GRANT EXECUTE ON FUNCTION record_publication(text, text, jsonb, jsonb, jsonb, jsonb, jsonb),
    settle_publication(text, text, boolean, jsonb), record_rollback(text, text, text) TO psst_platform_publisher;
SELECT apply_read_grants();
