-- A city's own Wikidata item, for when the boundary data doesn't link one. Its coordinate is the city's middle,
-- where research starts and coverage grows outward from.
SET search_path = psst, public;

ALTER TABLE cities ADD COLUMN wikidata_id text CHECK (wikidata_id ~ '^Q[1-9][0-9]*$');

DROP FUNCTION add_city(text, bigint, text, text[], integer);
CREATE FUNCTION add_city(p_token text, p_area bigint, p_slug text, p_languages text[], p_order integer,
                         p_wikidata text DEFAULT NULL) RETURNS bigint
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    system runs := run_for(p_token, ARRAY['system']);
    area areas;
BEGIN
    SELECT * INTO area FROM areas WHERE id = p_area;
    IF NOT FOUND OR area.level NOT IN ('city', 'region') OR area.is_point THEN
        RAISE EXCEPTION 'area % is not a city or region with a boundary', p_area USING ERRCODE = '22023';
    END IF;
    INSERT INTO cities (id, slug, name, country_code, local_languages, research_order, wikidata_id)
    VALUES (area.id, p_slug, area.name, area.country_code, coalesce(p_languages, '{}'), p_order, p_wikidata)
    ON CONFLICT (id) DO UPDATE SET slug = EXCLUDED.slug, local_languages = EXCLUDED.local_languages,
        research_order = EXCLUDED.research_order, wikidata_id = coalesce(EXCLUDED.wikidata_id, cities.wikidata_id);
    RETURN area.id;
END;
$$;
GRANT EXECUTE ON FUNCTION add_city(text, bigint, text, text[], integer, text) TO psst_platform_system;
SELECT apply_read_grants();
