-- The lifecycle (design.md, section 6): one state machine for every item, the revisions and claims that enter
-- it, the checks recorded against them, and the evaluation that accepts a revision or sends it back. These are
-- the only code paths that write items, revisions, claims, evidence, checks, or transitions. Callers reach
-- them through the task and console functions, which check the run token first.
SET search_path = psst, public;

-- Every allowed move. Anything else is refused.
CREATE TABLE lifecycle_moves (
    from_state text NOT NULL,
    to_state   text NOT NULL,
    PRIMARY KEY (from_state, to_state)
);
INSERT INTO lifecycle_moves VALUES
    ('draft', 'checking'), ('draft', 'retired'),
    ('checking', 'draft'), ('checking', 'accepted'), ('checking', 'retired'),
    ('accepted', 'checking'), ('accepted', 'draft'), ('accepted', 'published'), ('accepted', 'retired'),
    ('published', 'checking'), ('published', 'draft'), ('published', 'retired');

CREATE FUNCTION transition(p_item text, p_to text, p_run text, p_task text, p_reason text) RETURNS void
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
END;
$$;

-- Revisions ------------------------------------------------------------------------------------------------

-- Stores a new revision with its claims and evidence and submits it for checking. Creates the item when
-- `p_item` is null. `p_claims` is a list of {text, kind, values, evidence: [{snapshot, quote}]}.
CREATE FUNCTION create_revision(
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
        INSERT INTO claims (id, revision_id, n, text, kind, "values")
        VALUES (claim_id, revision_id, n, claim ->> 'text', claim ->> 'kind', coalesce(claim -> 'values', '[]'));
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

-- Checks -----------------------------------------------------------------------------------------------------

-- Records one verdict. Enforces who may give it: tool checks only by the system, editor checks only by an
-- editor, and every model check by a run other than the one that wrote the revision. The two claim checks of a
-- claim come from different runs.
CREATE FUNCTION record_check(
    p_run text, p_task text, p_revision text, p_claim text, p_kind text, p_verdict text, p_note text,
    p_details jsonb DEFAULT '{}'
) RETURNS bigint
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs;
    revision revisions;
    item items;
    check_id bigint;
BEGIN
    SELECT * INTO run FROM runs WHERE id = p_run;
    SELECT * INTO revision FROM revisions WHERE id = p_revision;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'unknown revision %', p_revision USING ERRCODE = 'P0002';
    END IF;
    SELECT * INTO item FROM items WHERE id = revision.item_id;
    IF p_claim IS NOT NULL AND NOT EXISTS (SELECT 1 FROM claims WHERE id = p_claim AND revision_id = p_revision) THEN
        RAISE EXCEPTION 'claim % isn''t part of revision %', p_claim, p_revision USING ERRCODE = '22023';
    END IF;
    IF p_kind = 'tool' AND run.kind <> 'system' THEN
        RAISE EXCEPTION 'only the system records tool checks' USING ERRCODE = '42501';
    ELSIF p_kind = 'editor' AND run.kind <> 'editor' THEN
        RAISE EXCEPTION 'only an editor records editor checks' USING ERRCODE = '42501';
    ELSIF p_kind NOT IN ('tool', 'editor') AND run.kind <> 'worker' THEN
        RAISE EXCEPTION 'model checks are recorded by worker runs' USING ERRCODE = '42501';
    END IF;
    IF p_kind <> 'tool' AND run.id = revision.created_by_run THEN
        RAISE EXCEPTION 'a run never checks its own writing' USING ERRCODE = '42501';
    END IF;
    IF p_kind IN ('claim_a', 'claim_b') AND EXISTS (
        SELECT 1 FROM checks WHERE claim_id = p_claim AND run_id = run.id AND kind IN ('claim_a', 'claim_b')
          AND created_at >= item.checking_since) THEN
        RAISE EXCEPTION 'the two checks of a claim come from different runs' USING ERRCODE = '42501';
    END IF;
    IF p_kind = 'audit' THEN
        IF item.state <> 'accepted' OR item.current_revision <> p_revision THEN
            RAISE EXCEPTION 'audits check accepted revisions' USING ERRCODE = 'P0001';
        END IF;
    ELSIF p_kind <> 'editor' AND (item.state <> 'checking' OR item.current_revision <> p_revision) THEN
        RAISE EXCEPTION 'revision % isn''t being checked', p_revision USING ERRCODE = 'P0001';
    END IF;
    INSERT INTO checks (revision_id, claim_id, kind, run_id, task_id, model, verdict, note, details)
    VALUES (p_revision, p_claim, p_kind, run.id, p_task, run.model, p_verdict, p_note, coalesce(p_details, '{}'))
    RETURNING id INTO check_id;
    RETURN check_id;
END;
$$;

-- Evaluation -------------------------------------------------------------------------------------------------

-- Where a revision under check stands, from the checks recorded since it entered checking:
--   wait      checks still missing
--   escalate  claims (or the item) need an escalation: the two checks disagree, or one is unclear
--   revise    a claim is unsupported or contradicted, the tool check or item check failed
--   accept    everything passed
-- Editor verdicts outrank escalations, which outrank the first checks.
CREATE FUNCTION evaluate(p_revision text) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    revision revisions;
    item items;
    since timestamptz;
    tool checks;
    whole text;
    claim record;
    final text;
    problems jsonb := '[]';
    escalate_claims jsonb := '[]';
    escalate_item boolean := false;
    waiting boolean := false;
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

    FOR claim IN
        SELECT c.id, c.n,
               (SELECT verdict FROM checks k WHERE k.claim_id = c.id AND k.kind = 'editor' AND k.created_at >= since
                ORDER BY k.id DESC LIMIT 1) AS editor,
               (SELECT verdict FROM checks k WHERE k.claim_id = c.id AND k.kind = 'escalation' AND k.created_at >= since
                ORDER BY k.id DESC LIMIT 1) AS escalation,
               (SELECT verdict FROM checks k WHERE k.claim_id = c.id AND k.kind = 'claim_a' AND k.created_at >= since
                ORDER BY k.id DESC LIMIT 1) AS a,
               (SELECT verdict FROM checks k WHERE k.claim_id = c.id AND k.kind = 'claim_b' AND k.created_at >= since
                ORDER BY k.id DESC LIMIT 1) AS b
        FROM claims c WHERE c.revision_id = p_revision ORDER BY c.n
    LOOP
        final := coalesce(claim.editor, claim.escalation);
        IF final IS NULL THEN
            IF claim.a IS NULL OR claim.b IS NULL THEN
                waiting := true;
                CONTINUE;
            ELSIF claim.a = 'supported' AND claim.b = 'supported' THEN
                final := 'supported';
            ELSE
                escalate_claims := escalate_claims || to_jsonb(claim.id);
                CONTINUE;
            END IF;
        END IF;
        IF final <> 'supported' THEN
            problems := problems || to_jsonb(format('claim %s is %s', claim.n, final));
        END IF;
    END LOOP;

    SELECT verdict INTO whole FROM checks
    WHERE revision_id = p_revision AND claim_id IS NULL AND kind IN ('editor', 'escalation') AND created_at >= since
    ORDER BY CASE kind WHEN 'editor' THEN 0 ELSE 1 END, id DESC LIMIT 1;
    IF whole IS NULL THEN
        SELECT verdict INTO whole FROM checks
        WHERE revision_id = p_revision AND claim_id IS NULL AND kind IN ('item', 'translation') AND created_at >= since
        ORDER BY id DESC LIMIT 1;
        IF whole IS NULL THEN
            waiting := true;
        ELSIF whole = 'unclear' THEN
            escalate_item := true;
        END IF;
    END IF;
    IF whole IN ('fail', 'unclear') AND NOT escalate_item THEN
        problems := problems || to_jsonb('the whole-item check failed'::text);
    END IF;

    IF jsonb_array_length(problems) > 0 THEN
        RETURN jsonb_build_object('outcome', 'revise', 'problems', problems);
    ELSIF jsonb_array_length(escalate_claims) > 0 OR escalate_item THEN
        RETURN jsonb_build_object('outcome', 'escalate', 'claims', escalate_claims, 'item', escalate_item);
    ELSIF waiting THEN
        RETURN jsonb_build_object('outcome', 'wait');
    END IF;
    RETURN jsonb_build_object('outcome', 'accept');
END;
$$;

-- Applies an evaluation: accepts the revision or sends it back to its writer. Returns the evaluation.
CREATE FUNCTION settle(p_run text, p_task text, p_revision text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    result jsonb := evaluate(p_revision);
    item_id text := (SELECT item_id FROM revisions WHERE id = p_revision);
BEGIN
    IF result ->> 'outcome' = 'accept' THEN
        PERFORM transition(item_id, 'accepted', p_run, p_task, 'every check passed');
    ELSIF result ->> 'outcome' = 'revise' THEN
        PERFORM transition(item_id, 'draft', p_run, p_task,
                           'sent back: ' || (SELECT string_agg(value, '; ') FROM jsonb_array_elements_text(result -> 'problems')));
    END IF;
    RETURN result;
END;
$$;

CREATE FUNCTION retire(p_run text, p_item text, p_reason text) RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
BEGIN
    PERFORM transition(p_item, 'retired', p_run, NULL, p_reason);
    -- A translation never outlives the item it translates.
    PERFORM transition(t.id, 'retired', p_run, NULL, 'the item it translates was retired')
    FROM items t WHERE t.translates = p_item AND t.state <> 'retired';
END;
$$;
