-- Content items, revisions, sources, snapshots, claims, evidence, checks, and history (design.md, section 5).
SET search_path = psst, public;

-- Tags -------------------------------------------------------------------------------------------------------

CREATE TABLE tags (
    id             text PRIMARY KEY CHECK (id ~ id_pattern('tg', 8)),
    canonical_name text NOT NULL CHECK (canonical_name <> ''),
    type           text NOT NULL CHECK (type IN ('person_or_group', 'event', 'era', 'theme', 'movement')),
    wikidata_id    text UNIQUE CHECK (wikidata_id ~ '^Q[1-9][0-9]*$'),
    created_by_run text REFERENCES runs,
    created_at     timestamptz NOT NULL DEFAULT now()
);

-- The canonical name and every alias, normalized (lowercase, no accents, no leading "the", collapsed
-- punctuation), unique across all tags so "Beatles" and "The Beatles" can't both exist.
CREATE TABLE tag_labels (
    normalized   text PRIMARY KEY,
    tag_id       text NOT NULL REFERENCES tags ON DELETE CASCADE,
    label        text NOT NULL,
    is_canonical boolean NOT NULL DEFAULT false
);
CREATE UNIQUE INDEX tag_labels_one_canonical ON tag_labels (tag_id) WHERE is_canonical;
CREATE INDEX tag_labels_trgm_idx ON tag_labels USING gin (normalized gin_trgm_ops);

CREATE TABLE tag_names (
    tag_id text NOT NULL REFERENCES tags ON DELETE CASCADE,
    lang   text NOT NULL,
    name   text NOT NULL,
    PRIMARY KEY (tag_id, lang)
);

-- Items and revisions ----------------------------------------------------------------------------------------

CREATE TABLE item_types (
    name          text PRIMARY KEY CHECK (name ~ '^[a-z]+$'),
    place_scoped  boolean NOT NULL,
    description   text NOT NULL
);
INSERT INTO item_types (name, place_scoped, description) VALUES
    ('story', true, 'A surprising, sourced story about one place.'),
    ('guide', true, 'Plain guide information about one place: identifier, About, and key facts.'),
    ('photo', true, 'A current or historic photo of one place.'),
    ('trail', false, 'A themed walk linking places that have published stories.'),
    ('translation', false, 'A checked translation of an accepted story, guide, or trail.');

CREATE TABLE items (
    id                 text PRIMARY KEY CHECK (id ~ id_pattern('it')),
    type               text NOT NULL REFERENCES item_types,
    place_id           text REFERENCES places,
    city_id            bigint NOT NULL REFERENCES cities,
    translates         text REFERENCES items,
    language           text NOT NULL DEFAULT 'en' CHECK (language IN ('en', 'zh-Hans')),
    state              text NOT NULL DEFAULT 'draft'
                       CHECK (state IN ('draft', 'checking', 'accepted', 'published', 'retired')),
    current_revision   text,
    published_revision text,
    position           integer NOT NULL DEFAULT 0,
    checking_since     timestamptz,
    created_by_run     text NOT NULL REFERENCES runs,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),
    CHECK ((type = 'translation') = (translates IS NOT NULL)),
    CHECK ((type = 'translation') = (language <> 'en'))
);
CREATE UNIQUE INDEX items_one_translation ON items (translates, language) WHERE translates IS NOT NULL;
CREATE INDEX items_place_idx ON items (place_id, type, position);
CREATE INDEX items_city_state_idx ON items (city_id, type, state);
CREATE INDEX items_state_idx ON items (state, updated_at);
CREATE TRIGGER items_touch BEFORE UPDATE ON items FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

-- An item's state changes only inside the lifecycle function, which records the transition.
CREATE FUNCTION guard_item_state() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.state IS DISTINCT FROM OLD.state AND current_setting('psst.in_transition', true) IS DISTINCT FROM 'on' THEN
        RAISE EXCEPTION 'item state changes only through psst.transition' USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER items_state_guard BEFORE UPDATE OF state ON items FOR EACH ROW EXECUTE FUNCTION guard_item_state();

CREATE TABLE revisions (
    id             text PRIMARY KEY CHECK (id ~ id_pattern('rv')),
    item_id        text NOT NULL REFERENCES items,
    number         integer NOT NULL CHECK (number >= 1),
    translation_of text REFERENCES revisions,
    body           jsonb NOT NULL CHECK (jsonb_typeof(body) = 'object'),
    rulebook       text NOT NULL CHECK (rulebook ~ '^[0-9a-f]{12}$'),
    created_by_run text NOT NULL REFERENCES runs,
    created_by_task text,
    created_at     timestamptz NOT NULL DEFAULT now(),
    reason         text NOT NULL CHECK (reason <> ''),
    UNIQUE (item_id, number)
);
CREATE INDEX revisions_run_idx ON revisions (created_by_run);
CREATE INDEX revisions_translation_idx ON revisions (translation_of) WHERE translation_of IS NOT NULL;
CREATE TRIGGER revisions_history BEFORE UPDATE OR DELETE ON revisions FOR EACH ROW EXECUTE FUNCTION refuse_change();

ALTER TABLE items
    ADD FOREIGN KEY (current_revision) REFERENCES revisions DEFERRABLE INITIALLY DEFERRED,
    ADD FOREIGN KEY (published_revision) REFERENCES revisions DEFERRABLE INITIALLY DEFERRED;

-- The tags a revision names, kept as rows so every id is checked and tag pages are one index lookup.
CREATE TABLE revision_tags (
    revision_id text NOT NULL REFERENCES revisions,
    tag_id      text NOT NULL REFERENCES tags,
    PRIMARY KEY (revision_id, tag_id)
);
CREATE INDEX revision_tags_tag_idx ON revision_tags (tag_id);

-- Sources and snapshots --------------------------------------------------------------------------------------

CREATE TABLE sources (
    id            text PRIMARY KEY CHECK (id ~ id_pattern('so')),
    url           text NOT NULL CHECK (url ~ '^https://'),
    url_key       text NOT NULL UNIQUE,
    title         text NOT NULL CHECK (title <> ''),
    publisher     text NOT NULL CHECK (publisher <> ''),
    kind          text NOT NULL CHECK (kind IN ('official_record', 'archive', 'operator', 'scholarly', 'press',
                                                'reference', 'community')),
    language      text NOT NULL,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    created_by_run text NOT NULL REFERENCES runs
);

-- What a source said when it was read. Written only by the fetch service, never changed. The text is
-- normalized plain text; quotes are matched against it.
CREATE TABLE snapshots (
    id           text PRIMARY KEY CHECK (id ~ id_pattern('sn')),
    source_id    text NOT NULL REFERENCES sources,
    fetched_at   timestamptz NOT NULL DEFAULT now(),
    http_status  integer NOT NULL,
    via          text NOT NULL CHECK (via IN ('live', 'archive', 'mirror')),
    read_url     text NOT NULL,
    title        text,
    content_hash bytea NOT NULL,
    text         text NOT NULL CHECK (text <> ''),
    run_id       text NOT NULL REFERENCES runs,
    UNIQUE (source_id, content_hash)
);
CREATE INDEX snapshots_source_idx ON snapshots (source_id, fetched_at DESC);
CREATE TRIGGER snapshots_history BEFORE UPDATE OR DELETE ON snapshots FOR EACH ROW EXECUTE FUNCTION refuse_change();

-- Claims and evidence ----------------------------------------------------------------------------------------

CREATE TABLE claims (
    id          text PRIMARY KEY CHECK (id ~ id_pattern('cl')),
    revision_id text NOT NULL REFERENCES revisions,
    n           integer NOT NULL CHECK (n >= 1),
    text        text NOT NULL CHECK (text <> ''),
    kind        text NOT NULL CHECK (kind IN ('date', 'name', 'number', 'place', 'event', 'attribute')),
    "values"    jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof("values") = 'array'),
    UNIQUE (revision_id, n)
);
CREATE TRIGGER claims_history BEFORE UPDATE OR DELETE ON claims FOR EACH ROW EXECUTE FUNCTION refuse_change();

CREATE TABLE evidence (
    id          bigserial PRIMARY KEY,
    claim_id    text NOT NULL REFERENCES claims,
    snapshot_id text NOT NULL REFERENCES snapshots,
    quote       text NOT NULL CHECK (char_length(quote) BETWEEN 1 AND 2000),
    quote_start integer,
    quote_end   integer,
    matched     boolean,
    CHECK ((matched IS TRUE) = (quote_start IS NOT NULL AND quote_end IS NOT NULL))
);
CREATE INDEX evidence_claim_idx ON evidence (claim_id);
CREATE INDEX evidence_snapshot_idx ON evidence (snapshot_id);

-- Evidence is written once; only the tool check fills in whether and where the quote was found, once.
CREATE FUNCTION guard_evidence() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' OR OLD.matched IS NOT NULL
       OR (NEW.claim_id, NEW.snapshot_id, NEW.quote) IS DISTINCT FROM (OLD.claim_id, OLD.snapshot_id, OLD.quote) THEN
        RAISE EXCEPTION 'evidence is never changed once checked' USING ERRCODE = 'P0001';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER evidence_history BEFORE UPDATE OR DELETE ON evidence FOR EACH ROW EXECUTE FUNCTION guard_evidence();

-- Checks and history -----------------------------------------------------------------------------------------

CREATE TABLE checks (
    id          bigserial PRIMARY KEY,
    revision_id text NOT NULL REFERENCES revisions,
    claim_id    text REFERENCES claims,
    kind        text NOT NULL CHECK (kind IN ('tool', 'claim_a', 'claim_b', 'item', 'escalation', 'audit', 'editor',
                                              'translation')),
    run_id      text NOT NULL REFERENCES runs,
    task_id     text,
    model       text,
    verdict     text NOT NULL CHECK (verdict IN ('supported', 'unsupported', 'contradicted', 'unclear', 'pass', 'fail')),
    note        text NOT NULL CHECK (note <> ''),
    details     jsonb NOT NULL DEFAULT '{}',
    created_at  timestamptz NOT NULL DEFAULT now(),
    CHECK ((claim_id IS NULL) = (verdict IN ('pass', 'fail') OR kind IN ('tool', 'item', 'translation'))),
    CHECK (kind NOT IN ('tool', 'item', 'translation') OR claim_id IS NULL),
    CHECK (kind NOT IN ('claim_a', 'claim_b') OR claim_id IS NOT NULL)
);
CREATE INDEX checks_revision_idx ON checks (revision_id, kind, created_at);
CREATE INDEX checks_claim_idx ON checks (claim_id, kind, created_at) WHERE claim_id IS NOT NULL;
CREATE INDEX checks_run_idx ON checks (run_id);
CREATE TRIGGER checks_history BEFORE UPDATE OR DELETE ON checks FOR EACH ROW EXECUTE FUNCTION refuse_change();

CREATE TABLE transitions (
    id          bigserial PRIMARY KEY,
    item_id     text NOT NULL REFERENCES items,
    from_state  text,
    to_state    text NOT NULL,
    revision_id text REFERENCES revisions,
    run_id      text NOT NULL REFERENCES runs,
    task_id     text,
    reason      text NOT NULL CHECK (reason <> ''),
    at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX transitions_item_idx ON transitions (item_id, at);
CREATE INDEX transitions_at_idx ON transitions (at DESC);
CREATE TRIGGER transitions_history BEFORE UPDATE OR DELETE ON transitions FOR EACH ROW EXECUTE FUNCTION refuse_change();

-- Problem reports from readers. A report never changes content by itself; it sends the item back to checking.
CREATE TABLE reports (
    id          bigserial PRIMARY KEY,
    item_id     text NOT NULL REFERENCES items,
    reason      text NOT NULL CHECK (reason IN ('wrong', 'outdated', 'location', 'offensive', 'other')),
    message     text CHECK (char_length(message) <= 1000),
    app_version text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    state       text NOT NULL DEFAULT 'open' CHECK (state IN ('open', 'resolved')),
    resolution  text,
    resolved_by text REFERENCES runs,
    resolved_at timestamptz,
    CHECK ((state = 'resolved') = (resolved_at IS NOT NULL AND resolution IS NOT NULL))
);
CREATE INDEX reports_open_idx ON reports (created_at) WHERE state = 'open';
CREATE INDEX reports_item_idx ON reports (item_id);
