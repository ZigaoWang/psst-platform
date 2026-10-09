-- Evidence (design.md, section 7): snapshots written by the fetch service, the role a claim plays in a story,
-- and tool check results.
SET search_path = psst, public;

-- A story that sets the record straight states the popular version in claims with the role `myth`; the
-- source rules check those and the correcting claims separately.
ALTER TABLE claims ADD COLUMN role text NOT NULL DEFAULT 'fact' CHECK (role IN ('fact', 'myth'));

-- Stores what a source said, for the worker or editor run that asked to read it. Called only by the fetch
-- service (the system role), which read the page itself. A source keeps the title, publisher, kind, and
-- language it was first stored with; an editor corrects them. Returns the source, its kind, and the snapshot.
CREATE FUNCTION record_snapshot(
    p_system_token text, p_reader_token text, p_url text, p_url_key text, p_title text, p_publisher text,
    p_kind text, p_language text, p_status integer, p_via text, p_read_url text, p_page_title text, p_text text
) RETURNS TABLE (source_id text, source_kind text, snapshot_id text, is_new boolean)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    system runs := run_for(p_system_token, ARRAY['system']);
    reader runs;
    hash bytea := digest(p_text, 'sha256');
BEGIN
    SELECT * INTO reader FROM runs WHERE token_hash = digest(coalesce(p_reader_token, ''), 'sha256');
    IF NOT FOUND OR reader.ended_at IS NOT NULL OR reader.kind NOT IN ('worker', 'editor') THEN
        RAISE EXCEPTION 'reading needs an open worker or editor run' USING ERRCODE = '28000';
    END IF;
    INSERT INTO sources (id, url, url_key, title, publisher, kind, language, created_by_run)
    VALUES (new_id('so'), p_url, p_url_key, p_title, p_publisher, p_kind, p_language, reader.id)
    ON CONFLICT (url_key) DO NOTHING;
    SELECT s.id, s.kind INTO source_id, source_kind FROM sources s WHERE s.url_key = p_url_key;
    SELECT s.id INTO snapshot_id FROM snapshots s WHERE s.source_id = record_snapshot.source_id AND s.content_hash = hash;
    is_new := snapshot_id IS NULL;
    IF is_new THEN
        snapshot_id := new_id('sn');
        INSERT INTO snapshots (id, source_id, http_status, via, read_url, title, content_hash, text, run_id)
        VALUES (snapshot_id, record_snapshot.source_id, p_status, p_via, p_read_url, nullif(p_page_title, ''), hash,
                p_text, reader.id);
    END IF;
    RETURN NEXT;
END;
$$;

-- Records the tool check of a revision: where each quote was found (or that it wasn't), and the verdict.
-- `p_matches` is a list of {evidence, start, end}, with start and end null for a quote that wasn't found.
CREATE FUNCTION record_tool_check(p_token text, p_task text, p_revision text, p_pass boolean, p_note text,
                                  p_details jsonb, p_matches jsonb) RETURNS bigint
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    system runs := run_for(p_token, ARRAY['system']);
    found jsonb;
BEGIN
    FOR found IN SELECT value FROM jsonb_array_elements(coalesce(p_matches, '[]')) LOOP
        UPDATE evidence e
        SET matched = (found ->> 'start') IS NOT NULL,
            quote_start = (found ->> 'start')::integer,
            quote_end = (found ->> 'end')::integer
        FROM claims c
        WHERE e.id = (found ->> 'evidence')::bigint AND c.id = e.claim_id AND c.revision_id = p_revision
          AND e.matched IS NULL;
    END LOOP;
    RETURN record_check(system.id, p_task, p_revision, NULL, 'tool', CASE WHEN p_pass THEN 'pass' ELSE 'fail' END,
                        p_note, p_details);
END;
$$;

-- create_revision, now storing each claim's role.
CREATE OR REPLACE FUNCTION create_revision(
    p_run text, p_task text, p_item text, p_type text, p_place text, p_city bigint, p_translates text,
    p_translation_of text, p_language text, p_body jsonb, p_claims jsonb, p_rulebook text, p_reason text
) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    item items;
    place places;
    revision_id text := new_id('rv');
    claim jsonb;
    claim_id text;
    proof jsonb;
    n integer := 0;
    city bigint := p_city;
BEGIN
    IF p_item IS NULL THEN
        IF NOT EXISTS (SELECT 1 FROM item_types WHERE name = p_type) THEN
            RAISE EXCEPTION 'unknown item type %', p_type USING ERRCODE = '22023';
        END IF;
        IF p_type = 'translation' THEN
            SELECT * INTO item FROM items WHERE id = p_translates;
            IF NOT FOUND OR item.type = 'translation' THEN
                RAISE EXCEPTION 'a translation translates a story, guide, or trail' USING ERRCODE = '22023';
            END IF;
            place.id := item.place_id;
            city := item.city_id;
        ELSIF (SELECT place_scoped FROM item_types WHERE name = p_type) THEN
            SELECT * INTO place FROM places WHERE id = p_place;
            IF NOT FOUND OR place.state NOT IN ('pending', 'active') THEN
                RAISE EXCEPTION 'a % needs a pending or active place', p_type USING ERRCODE = '22023';
            END IF;
            city := coalesce(place.city_id, place.region_id, p_city);
        ELSIF p_place IS NOT NULL THEN
            RAISE EXCEPTION 'a % isn''t about one place', p_type USING ERRCODE = '22023';
        END IF;
        IF city IS NULL OR NOT EXISTS (SELECT 1 FROM cities WHERE id = city) THEN
            RAISE EXCEPTION 'the item''s city isn''t set up' USING ERRCODE = '22023';
        END IF;
        INSERT INTO items (id, type, place_id, city_id, translates, language, position, created_by_run)
        VALUES (new_id('it'), p_type, place.id, city, CASE WHEN p_type = 'translation' THEN p_translates END,
                CASE WHEN p_type = 'translation' THEN p_language ELSE 'en' END,
                coalesce((SELECT max(position) + 1 FROM items WHERE place_id = place.id AND type = p_type), 0),
                p_run)
        RETURNING * INTO item;
        INSERT INTO transitions (item_id, from_state, to_state, run_id, task_id, reason)
        VALUES (item.id, NULL, 'draft', p_run, p_task, p_reason);
    ELSE
        SELECT * INTO item FROM items WHERE id = p_item FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'unknown item %', p_item USING ERRCODE = 'P0002';
        END IF;
        IF item.state NOT IN ('draft', 'accepted', 'published') THEN
            RAISE EXCEPTION 'item % is %; a new revision waits until its checks finish', item.id, item.state
                USING ERRCODE = 'P0001';
        END IF;
    END IF;

    IF item.type = 'translation' THEN
        IF p_translation_of IS NULL OR NOT EXISTS (
            SELECT 1 FROM revisions WHERE id = p_translation_of AND item_id = item.translates) THEN
            RAISE EXCEPTION 'a translation names the revision of % it translates', item.translates USING ERRCODE = '22023';
        END IF;
        IF jsonb_array_length(coalesce(p_claims, '[]')) > 0 THEN
            RAISE EXCEPTION 'a translation carries the claims of the revision it translates' USING ERRCODE = '22023';
        END IF;
    ELSIF p_translation_of IS NOT NULL THEN
        RAISE EXCEPTION 'only translations name a revision they translate' USING ERRCODE = '22023';
    END IF;

    INSERT INTO revisions (id, item_id, number, translation_of, body, rulebook, created_by_run, created_by_task, reason)
    VALUES (revision_id, item.id, coalesce((SELECT max(number) + 1 FROM revisions WHERE item_id = item.id), 1),
            p_translation_of, p_body, p_rulebook, p_run, p_task, p_reason);

    INSERT INTO revision_tags (revision_id, tag_id)
    SELECT revision_id, value FROM jsonb_array_elements_text(coalesce(p_body -> 'tags', '[]'));

    FOR claim IN SELECT value FROM jsonb_array_elements(coalesce(p_claims, '[]')) LOOP
        n := n + 1;
        claim_id := new_id('cl');
        INSERT INTO claims (id, revision_id, n, text, kind, "values", role)
        VALUES (claim_id, revision_id, n, claim ->> 'text', claim ->> 'kind', coalesce(claim -> 'values', '[]'),
                coalesce(claim ->> 'role', 'fact'));
        IF jsonb_array_length(coalesce(claim -> 'evidence', '[]')) = 0 THEN
            RAISE EXCEPTION 'claim % has no evidence', n USING ERRCODE = '22023';
        END IF;
        FOR proof IN SELECT value FROM jsonb_array_elements(claim -> 'evidence') LOOP
            INSERT INTO evidence (claim_id, snapshot_id, quote) VALUES (claim_id, proof ->> 'snapshot', proof ->> 'quote');
        END LOOP;
    END LOOP;

    UPDATE items SET current_revision = revision_id WHERE id = item.id;
    PERFORM transition(item.id, 'checking', p_run, p_task, p_reason);
    RETURN revision_id;
END;
$$;

GRANT EXECUTE ON FUNCTION record_snapshot(text, text, text, text, text, text, text, text, integer, text, text, text, text),
    record_tool_check(text, text, text, boolean, text, jsonb, jsonb) TO psst_platform_system;
SELECT apply_read_grants();
