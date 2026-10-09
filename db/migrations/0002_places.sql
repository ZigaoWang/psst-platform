-- Areas, cities, places, and research coverage (design.md, sections 5.1, 5.5, and 10).
SET search_path = psst, public;

-- Boundaries from Who's On First (ids as published) and OpenStreetMap (negative relation ids). Reference
-- data: loaded by tools from public sources, never typed.
CREATE TABLE areas (
    id           bigint PRIMARY KEY,
    source       text NOT NULL CHECK (source IN ('wof', 'osm')),
    placetype    text NOT NULL,
    level        text NOT NULL CHECK (level IN ('country', 'region', 'city', 'district', 'neighborhood')),
    name         text NOT NULL CHECK (name <> ''),
    country_code text CHECK (country_code ~ '^[A-Z]{2}$'),
    parent_id    bigint,
    geom         geometry(Geometry, 4326) NOT NULL,
    is_point     boolean GENERATED ALWAYS AS (GeometryType(geom) = 'POINT') STORED,
    area_km2     double precision,
    license      text NOT NULL
);
CREATE INDEX areas_geom_idx ON areas USING gist (geom);
CREATE INDEX areas_level_idx ON areas (level, country_code);

CREATE TABLE area_names (
    area_id bigint NOT NULL REFERENCES areas ON DELETE CASCADE,
    lang    text NOT NULL,
    name    text NOT NULL CHECK (name <> ''),
    PRIMARY KEY (area_id, lang)
);

-- Each boundary cut into small polygons, so testing a point touches a few hundred vertices, not a country.
CREATE TABLE area_parts (
    area_id bigint NOT NULL REFERENCES areas ON DELETE CASCADE,
    geom    geometry(Polygon, 4326) NOT NULL
);
CREATE INDEX area_parts_geom_idx ON area_parts USING gist (geom);
CREATE INDEX area_parts_area_idx ON area_parts (area_id);

-- Cities set up for research. The id is the city's area id, which is also its id in the published output.
CREATE TABLE cities (
    id                 bigint PRIMARY KEY REFERENCES areas,
    slug               text NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
    name               text NOT NULL CHECK (name <> ''),
    country_code       text NOT NULL CHECK (country_code ~ '^[A-Z]{2}$'),
    local_languages    text[] NOT NULL DEFAULT '{}',
    research_order     integer NOT NULL,
    created_at         timestamptz NOT NULL DEFAULT now()
);

-- Places -----------------------------------------------------------------------------------------------------

-- One physical thing with a pin. A place starts `pending` with its Wikidata item or OSM element; the system
-- worker looks up the coordinate and areas and makes it `active`, or `refused` with the reason.
CREATE TABLE places (
    id              text PRIMARY KEY CHECK (id ~ id_pattern('pl')),
    kind            text NOT NULL CHECK (kind IN ('transit', 'crossing', 'street', 'building', 'worship', 'memorial',
                                                  'green', 'water', 'culture')),
    size            text NOT NULL DEFAULT 'medium' CHECK (size IN ('small', 'medium', 'large')),
    state           text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'active', 'refused', 'merged', 'gone')),
    state_reason    text,
    wikidata_id     text CHECK (wikidata_id ~ '^Q[1-9][0-9]*$'),
    osm_ref         text CHECK (osm_ref ~ '^(node|way|relation)/[1-9][0-9]*$'),
    geom            geometry(Point, 4326),
    coord_source    text CHECK (coord_source IN ('wikidata', 'osm')),
    coord_ref       text,
    h3_r7           text,
    country_code    text CHECK (country_code ~ '^[A-Z]{2}$'),
    region_id       bigint REFERENCES areas,
    city_id         bigint REFERENCES areas,
    district_id     bigint REFERENCES areas,
    neighborhood_id bigint REFERENCES areas,
    area_rules      jsonb NOT NULL DEFAULT '{}',
    merged_into     text REFERENCES places,
    created_by_run  text NOT NULL REFERENCES runs,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CHECK (wikidata_id IS NOT NULL OR osm_ref IS NOT NULL),
    CHECK (state IN ('pending', 'refused') OR (geom IS NOT NULL AND coord_source IS NOT NULL AND h3_r7 IS NOT NULL)),
    CHECK (coord_source IS NULL OR coord_ref = CASE coord_source WHEN 'wikidata' THEN wikidata_id ELSE osm_ref END),
    CHECK ((state = 'merged') = (merged_into IS NOT NULL)),
    CHECK (state NOT IN ('refused', 'merged', 'gone') OR state_reason IS NOT NULL)
);
-- A refused place doesn't hold on to its Wikidata item or OSM element.
CREATE UNIQUE INDEX places_wikidata_idx ON places (wikidata_id) WHERE state <> 'refused';
CREATE UNIQUE INDEX places_osm_idx ON places (osm_ref) WHERE state <> 'refused';
CREATE INDEX places_geom_idx ON places USING gist (geom);
CREATE INDEX places_cell_idx ON places (h3_r7);
CREATE INDEX places_city_idx ON places (city_id, id);
CREATE INDEX places_pending_idx ON places (created_at) WHERE state = 'pending';
CREATE TRIGGER places_touch BEFORE UPDATE ON places FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

-- 'display' is the English name shown, 'local' what the signs say, 'alt' established names in other languages.
CREATE TABLE place_names (
    place_id text NOT NULL REFERENCES places ON DELETE CASCADE,
    role     text NOT NULL CHECK (role IN ('display', 'local', 'alt')),
    lang     text NOT NULL CHECK (lang ~ '^[a-z]{2,3}(-[A-Za-z0-9]+)*$'),
    name     text NOT NULL CHECK (name <> '' AND name = btrim(name)),
    source   text NOT NULL CHECK (source IN ('wikidata', 'osm', 'research')),
    PRIMARY KEY (place_id, role, lang)
);
CREATE UNIQUE INDEX place_names_one_display ON place_names (place_id) WHERE role = 'display';
CREATE UNIQUE INDEX place_names_one_local ON place_names (place_id) WHERE role = 'local';
CREATE INDEX place_names_trgm_idx ON place_names USING gin (lower(name) gin_trgm_ops);

-- Ids from the previous system that resolve to a place: its `pl_` ids and the older `areaId/spotId` ids.
CREATE TABLE place_identity (
    legacy_id text PRIMARY KEY,
    place_id  text NOT NULL REFERENCES places,
    kind      text NOT NULL CHECK (kind IN ('place', 'spot'))
);
CREATE INDEX place_identity_place_idx ON place_identity (place_id);

-- The previous system's place list, used only as a coverage checklist and to keep ids (decisions in
-- design.md, section 3). No stories, guides, or photos are kept.
CREATE TABLE legacy_places (
    id           text PRIMARY KEY CHECK (id ~ id_pattern('pl')),
    name         text NOT NULL,
    local_name   text,
    wikidata_id  text CHECK (wikidata_id ~ '^Q[1-9][0-9]*$'),
    osm_ref      text CHECK (osm_ref ~ '^(node|way|relation)/[1-9][0-9]*$'),
    kind         text NOT NULL,
    geom         geometry(Point, 4326) NOT NULL,
    city_id      bigint,
    spot_ids     text[] NOT NULL DEFAULT '{}'
);
CREATE INDEX legacy_places_wikidata_idx ON legacy_places (wikidata_id);
CREATE INDEX legacy_places_osm_idx ON legacy_places (osm_ref);
CREATE INDEX legacy_places_geom_idx ON legacy_places USING gist (geom);

-- Research coverage ------------------------------------------------------------------------------------------

CREATE TABLE research_cells (
    cell               text PRIMARY KEY CHECK (cell ~ '^[0-9a-f]{15}$'),
    city_id            bigint NOT NULL REFERENCES cities,
    state              text NOT NULL DEFAULT 'open' CHECK (state IN ('open', 'queued', 'researched')),
    passes             integer NOT NULL DEFAULT 0,
    last_researched_at timestamptz,
    notes              text,
    geom               geometry(Polygon, 4326) NOT NULL
);
CREATE INDEX research_cells_city_idx ON research_cells (city_id, state);
CREATE INDEX research_cells_geom_idx ON research_cells USING gist (geom);

-- Candidate places for a cell, and how each was accounted for. A cell is researched only when every lead is
-- added, already known, or skipped with a reason.
CREATE TABLE leads (
    id           text PRIMARY KEY CHECK (id ~ id_pattern('ld')),
    cell         text NOT NULL REFERENCES research_cells,
    key          text NOT NULL,
    origin       text NOT NULL CHECK (origin IN ('wikipedia', 'osm', 'wikidata', 'legacy')),
    name         text NOT NULL CHECK (name <> ''),
    wikidata_id  text,
    osm_ref      text,
    url          text,
    what         text,
    fame         integer,
    legacy_place text REFERENCES legacy_places,
    status       text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'added', 'known', 'skipped', 'later')),
    reason       text,
    place_id     text REFERENCES places,
    decided_by   text REFERENCES runs,
    decided_at   timestamptz,
    found_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (cell, key),
    CHECK (status NOT IN ('skipped', 'later') OR reason IS NOT NULL),
    CHECK (status NOT IN ('added', 'known') OR place_id IS NOT NULL)
);
CREATE INDEX leads_open_idx ON leads (cell, fame DESC NULLS LAST) WHERE status IN ('open', 'later');
CREATE INDEX leads_wikidata_idx ON leads (wikidata_id);

-- Anonymous counts of empty map areas viewed in the app (H3 resolution 5 cells).
CREATE TABLE demand (
    cell  text NOT NULL CHECK (cell ~ '^[0-9a-f]{15}$'),
    day   date NOT NULL,
    count integer NOT NULL DEFAULT 0 CHECK (count >= 0),
    PRIMARY KEY (cell, day)
);
