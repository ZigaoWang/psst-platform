-- The golden bar (decision 25): a guide of worked examples showing what good looks like for each thing written.
-- It is content, so it lives here, versioned like the rulebook, never in git. Every research, review, and revision
-- task carries the current version, and every revision records the version it was written against.
SET search_path = psst, public;

CREATE TABLE guidance (
    name       text NOT NULL CHECK (name ~ '^[a-z_]+$'),
    version    text NOT NULL CHECK (version ~ '^[0-9a-f]{12}$'),
    body       text NOT NULL CHECK (body <> ''),
    note       text NOT NULL CHECK (note <> ''),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (name, version)
);
CREATE TRIGGER guidance_history BEFORE UPDATE OR DELETE ON guidance FOR EACH ROW EXECUTE FUNCTION refuse_change();

-- The newest version of a guidance document.
CREATE FUNCTION current_guidance(p_name text) RETURNS guidance
LANGUAGE sql STABLE SET search_path = psst, public, pg_temp AS $$
    SELECT * FROM guidance WHERE name = p_name ORDER BY created_at DESC, version LIMIT 1
$$;
GRANT EXECUTE ON FUNCTION current_guidance(text) TO psst_platform_worker, psst_platform_console, psst_platform_system;

ALTER TABLE revisions ADD COLUMN bar_version text;

DROP FUNCTION create_revision(text, text, text, text, text, bigint, text, text, text, jsonb, jsonb, text, text);
CREATE FUNCTION create_revision(
    p_run text, p_task text, p_item text, p_type text, p_place text, p_city bigint, p_translates text,
    p_translation_of text, p_language text, p_body jsonb, p_claims jsonb, p_rulebook text, p_reason text,
    p_bar text DEFAULT NULL
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

    INSERT INTO revisions (id, item_id, number, translation_of, body, rulebook, bar_version, created_by_run,
                           created_by_task, reason)
    VALUES (revision_id, item.id, coalesce((SELECT max(number) + 1 FROM revisions WHERE item_id = item.id), 1),
            p_translation_of, p_body, p_rulebook, p_bar, p_run, p_task, p_reason);

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

CREATE OR REPLACE FUNCTION submit_research(p_token text, p_task text, p_result jsonb, p_prompt text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['worker']);
    task tasks := held_task(run, p_task);
    target_cell text := task.input ->> 'cell';
    entry jsonb;
    story jsonb;
    place_id text;
    new_places text[] := '{}';
    places_by_index text[] := '{}';
    revisions text[] := '{}';
    lead jsonb;
    stories integer := 0;
    guides integer := 0;
    guides_skipped text[] := '{}';
    remaining integer;
    revision_id text;
BEGIN
    IF task.type <> 'research_cell' THEN
        RAISE EXCEPTION 'task % is not research', p_task USING ERRCODE = '22023';
    END IF;
    FOR entry IN SELECT value FROM jsonb_array_elements(coalesce(p_result -> 'places', '[]')) LOOP
        IF entry ? 'existing' THEN
            place_id := entry ->> 'existing';
            IF NOT EXISTS (SELECT 1 FROM places WHERE id = place_id AND state IN ('pending', 'active')) THEN
                RAISE EXCEPTION 'no place %', place_id USING ERRCODE = '22023';
            END IF;
        ELSE
            place_id := create_place(run.id, entry ->> 'wikidata', entry ->> 'osm', entry ->> 'kind', entry ->> 'size',
                                     entry ->> 'name', entry -> 'local_name');
            IF (SELECT state FROM places WHERE id = place_id) = 'pending' THEN
                new_places := new_places || place_id;
            END IF;
        END IF;
        places_by_index := places_by_index || place_id;
        FOR story IN SELECT value FROM jsonb_array_elements(coalesce(entry -> 'stories', '[]')) LOOP
            revision_id := create_revision(run.id, task.id, NULL, 'story', place_id, task.city_id, NULL, NULL, 'en',
                                           story -> 'body', story -> 'claims', p_result ->> 'rulebook',
                                           'researched in cell ' || target_cell, p_result ->> 'bar');
            revisions := revisions || revision_id;
            stories := stories + 1;
        END LOOP;
        IF entry ? 'guide' AND EXISTS (SELECT 1 FROM items i WHERE i.place_id = places_by_index[cardinality(places_by_index)]
                                       AND i.type = 'guide' AND i.state <> 'retired') THEN
            guides_skipped := guides_skipped || place_id;  -- another session wrote it first
        ELSIF entry ? 'guide' THEN
            revision_id := create_revision(run.id, task.id, NULL, 'guide', place_id, task.city_id, NULL, NULL, 'en',
                                           entry #> '{guide,body}', entry #> '{guide,claims}', p_result ->> 'rulebook',
                                           'researched in cell ' || target_cell, p_result ->> 'bar');
            revisions := revisions || revision_id;
            guides := guides + 1;
        END IF;
    END LOOP;
    FOR lead IN SELECT value FROM jsonb_array_elements(coalesce(p_result -> 'leads', '[]')) LOOP
        UPDATE leads SET status = lead ->> 'status', reason = lead ->> 'reason',
                         place_id = CASE WHEN lead ->> 'status' = 'added' THEN places_by_index[(lead ->> 'place')::integer + 1]
                                         ELSE coalesce(lead ->> 'existing', leads.place_id) END,
                         decided_by = run.id, decided_at = now()
        WHERE id = lead ->> 'lead' AND leads.cell = target_cell;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'lead % isn''t in cell %', lead ->> 'lead', target_cell USING ERRCODE = '22023';
        END IF;
    END LOOP;
    SELECT count(*) INTO remaining FROM leads l WHERE l.cell = target_cell AND l.status IN ('open', 'later');
    UPDATE research_cells SET passes = passes + 1, last_researched_at = now(), notes = p_result ->> 'notes',
                              state = CASE WHEN remaining = 0 THEN 'researched' ELSE 'open' END
    WHERE research_cells.cell = target_cell;
    IF cardinality(new_places) > 0 THEN
        PERFORM enqueue(run.id, 'resolve_places', 'resolve_places:' || p_task, jsonb_build_object('places', new_places),
                        task.city_id, NULL, NULL, NULL, '{}', NULL, 20);
    END IF;
    UPDATE tasks SET state = 'done', result = p_result, prompt = p_prompt, done_by = run.id, done_at = now(),
                     leased_by = NULL, leased_until = NULL
    WHERE id = task.id;
    FOR i IN 1 .. cardinality(revisions) LOOP
        PERFORM advance(run.id, revisions[i]);
    END LOOP;
    RETURN jsonb_build_object('places', cardinality(places_by_index), 'new_places', cardinality(new_places),
                              'stories', stories, 'guides', guides, 'leads_open', remaining,
                              'guides_skipped', to_jsonb(guides_skipped));
END;
$$;

CREATE OR REPLACE FUNCTION submit_task(p_token text, p_task text, p_result jsonb, p_prompt text DEFAULT NULL) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['worker', 'system']);
    task tasks := held_task(run, p_task);
    item items;
    claim_ids text[];
    entry record;
    decision jsonb;
    new_revision text;
    decided text[] := '{}';
    outcome jsonb := '{}';
    next jsonb := '{}';
BEGIN
    SELECT * INTO item FROM items WHERE id = task.item_id;
    CASE task.type
    WHEN 'audit' THEN
        claim_ids := ARRAY(SELECT id FROM claims WHERE revision_id = task.revision_id ORDER BY n);
        FOR entry IN SELECT * FROM verdicts_for(p_result, claim_ids) LOOP
            PERFORM record_check(run.id, task.id, task.revision_id, entry.id, 'audit', entry.verdict, entry.note);
        END LOOP;
        PERFORM record_check(run.id, task.id, task.revision_id, NULL, 'audit', p_result #>> '{item,verdict}',
                             p_result #>> '{item,note}', coalesce(p_result -> 'item', '{}'));
    WHEN 'review' THEN
        FOR decision IN SELECT value FROM jsonb_array_elements(coalesce(p_result -> 'decisions', '[]')) LOOP
            IF NOT task.input -> 'revisions' ? (decision ->> 'revision') THEN
                RAISE EXCEPTION 'revision % isn''t in this review', decision ->> 'revision' USING ERRCODE = '22023';
            END IF;
            decided := decided || (decision ->> 'revision');
        END LOOP;
        IF EXISTS (SELECT 1 FROM jsonb_array_elements_text(task.input -> 'revisions') AS r(id)
                   JOIN items i ON i.current_revision = r.id
                   WHERE i.state = 'checking' AND NOT r.id = ANY(decided)) THEN
            RAISE EXCEPTION 'decide every item in the review' USING ERRCODE = '22023';
        END IF;
    WHEN 'check_photo', 'check_translation' THEN
        IF p_result ->> 'verdict' = 'pass' AND jsonb_array_length(coalesce(p_result -> 'untraced', '[]')) > 0 THEN
            RAISE EXCEPTION 'details no claim states fail the check' USING ERRCODE = '22023';
        END IF;
        PERFORM record_check(run.id, task.id, task.revision_id, NULL,
                             CASE WHEN task.type = 'check_translation' THEN 'translation' ELSE 'item' END,
                             p_result ->> 'verdict', p_result ->> 'note', p_result);
    WHEN 'write_trail', 'revise', 'translate' THEN
        new_revision := create_revision(
            run.id, task.id,
            CASE WHEN task.type = 'revise' THEN task.item_id
                 WHEN task.type = 'translate' THEN (SELECT id FROM items WHERE translates = task.item_id
                                                     AND language = p_result ->> 'language' AND state <> 'retired')
            END,
            CASE task.type WHEN 'write_trail' THEN 'trail' WHEN 'translate' THEN 'translation' ELSE item.type END,
            task.place_id, task.city_id,
            CASE WHEN task.type = 'translate' THEN task.item_id END,
            CASE WHEN task.type = 'translate' THEN task.revision_id
                 WHEN task.type = 'revise' AND item.type = 'translation' THEN p_result ->> 'translation_of' END,
            coalesce(p_result ->> 'language', 'en'), p_result -> 'body', coalesce(p_result -> 'claims', '[]'),
            p_result ->> 'rulebook', coalesce(nullif(p_result ->> 'reason', ''), task.type), p_result ->> 'bar');
        outcome := jsonb_build_object('revision', new_revision);
    WHEN 'tool_check' THEN
        IF NOT EXISTS (SELECT 1 FROM checks c WHERE c.task_id = task.id AND c.kind = 'tool') THEN
            RAISE EXCEPTION 'record the tool check before submitting the task' USING ERRCODE = '22023';
        END IF;
    ELSE
        RAISE EXCEPTION 'task type % is submitted through its own command', task.type USING ERRCODE = '22023';
    END CASE;

    UPDATE tasks SET state = 'done', result = p_result, prompt = p_prompt, done_by = run.id, done_at = now(),
                     leased_by = NULL, leased_until = NULL
    WHERE id = task.id;

    IF task.type = 'audit' THEN
        outcome := outcome || jsonb_build_object('audit', settle_audit(run.id, (task.input ->> 'batch')));
    ELSIF task.type = 'review' THEN
        FOR decision IN SELECT value FROM jsonb_array_elements(p_result -> 'decisions') LOOP
            SELECT i.* INTO item FROM items i WHERE i.current_revision = decision ->> 'revision';
            IF NOT FOUND OR item.state <> 'checking' THEN
                CONTINUE;  -- retired meanwhile (its place was refused, for one)
            END IF;
            PERFORM record_check(run.id, task.id, decision ->> 'revision', NULL, 'review',
                                 CASE WHEN decision ->> 'decision' = 'reject' THEN 'fail' ELSE 'pass' END,
                                 decision ->> 'note',
                                 jsonb_build_object('decision', decision ->> 'decision',
                                                    'revisable', coalesce((decision ->> 'revisable')::boolean, false)));
            IF decision ->> 'decision' = 'edit' THEN
                PERFORM transition(item.id, 'draft', run.id, task.id, 'edited in review');
                new_revision := create_revision(run.id, task.id, item.id, item.type, item.place_id, item.city_id,
                                                NULL, NULL, 'en', decision -> 'body', coalesce(decision -> 'claims', '[]'),
                                                p_result ->> 'rulebook', 'edited in review: ' || (decision ->> 'note'),
                                                p_result ->> 'bar');
                next := next || jsonb_build_object(decision ->> 'revision', advance(run.id, new_revision));
            ELSE
                next := next || jsonb_build_object(decision ->> 'revision', advance(run.id, decision ->> 'revision'));
            END IF;
        END LOOP;
        PERFORM plan_review_audit(run.id, task.id);
        outcome := jsonb_build_object('decided', next);
    ELSE
        outcome := outcome || jsonb_build_object('next', advance(run.id, coalesce(new_revision, task.revision_id)));
    END IF;
    RETURN outcome;
END;
$$;

SELECT apply_read_grants();
