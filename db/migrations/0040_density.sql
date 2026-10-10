-- Density (decision 27): published things per H3 resolution 9 hexagon (about 100 meters across), against a target of
-- three in dense areas. The system worker fills each place's hexagon and the outline of every hexagon in the dense
-- research cells; the console draws them with the gaps highlighted.
SET search_path = psst, public;

ALTER TABLE places ADD COLUMN h3_r9 text;
CREATE INDEX places_h3_r9_idx ON places (h3_r9);

CREATE TABLE hexagons (
    cell     text PRIMARY KEY,
    city_id  bigint NOT NULL REFERENCES cities,
    parent   text NOT NULL,           -- the resolution 7 research cell it lies in
    geom     geometry(Polygon, 4326) NOT NULL
);
CREATE INDEX hexagons_city_idx ON hexagons (city_id);

INSERT INTO settings (key, value, note) VALUES
    ('density.target', '3', 'Published things per resolution 9 hexagon wanted in dense areas.');

-- What a reader finds in each hexagon: published stories, and places published with their guide alone.
CREATE VIEW hexagon_density AS
    SELECT h.cell, h.city_id, h.parent, h.geom,
           count(DISTINCT i.id) FILTER (WHERE i.type = 'story') AS stories,
           count(DISTINCT i.id) FILTER (WHERE i.type = 'story' AND i.tier = 'featured') AS featured,
           count(DISTINCT p.id) FILTER (WHERE i.type = 'guide' AND NOT EXISTS (
               SELECT 1 FROM items s WHERE s.place_id = p.id AND s.type = 'story' AND s.state = 'published'))
               AS guide_only
    FROM hexagons h
    LEFT JOIN places p ON p.h3_r9 = h.cell AND p.state = 'active'
    LEFT JOIN items i ON i.place_id = p.id AND i.state = 'published' AND i.type IN ('story', 'guide')
    GROUP BY h.cell, h.city_id, h.parent, h.geom;

CREATE FUNCTION record_hexagons(p_token text, p_places jsonb, p_hexagons jsonb) RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['system']);
BEGIN
    UPDATE places p SET h3_r9 = x ->> 'cell' FROM jsonb_array_elements(coalesce(p_places, '[]')) x
    WHERE p.id = x ->> 'place';
    INSERT INTO hexagons (cell, city_id, parent, geom)
    SELECT x ->> 'cell', (x ->> 'city')::bigint, x ->> 'parent', ST_SetSRID(ST_GeomFromGeoJSON(x ->> 'geom'), 4326)
    FROM jsonb_array_elements(coalesce(p_hexagons, '[]')) x
    ON CONFLICT (cell) DO NOTHING;
    RETURN jsonb_array_length(coalesce(p_places, '[]')) + jsonb_array_length(coalesce(p_hexagons, '[]'));
END;
$$;

GRANT EXECUTE ON FUNCTION record_hexagons(text, jsonb, jsonb) TO psst_platform_system;
SELECT apply_read_grants();
