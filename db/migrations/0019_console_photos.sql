-- Queueing photo searches from the console, for places with accepted or published stories and no photo yet.
SET search_path = psst, public;

CREATE FUNCTION console_queue_photos(p_token text, p_city bigint, p_limit integer) RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run text := console_act(p_token, 'queue photo searches', p_city::text, jsonb_build_object('limit', p_limit));
    queued integer := 0;
    place record;
BEGIN
    FOR place IN
        SELECT p.id FROM places p
        WHERE p.city_id = p_city AND p.state = 'active'
          AND EXISTS (SELECT 1 FROM items i WHERE i.place_id = p.id AND i.type = 'story'
                      AND i.state IN ('accepted', 'published'))
          AND NOT EXISTS (SELECT 1 FROM items i WHERE i.place_id = p.id AND i.type = 'photo' AND i.state <> 'retired')
          AND NOT EXISTS (SELECT 1 FROM tasks t WHERE t.place_id = p.id AND t.type IN ('find_photos', 'import_photo')
                          AND t.state IN ('queued', 'leased'))
        ORDER BY p.id LIMIT least(p_limit, 200)
    LOOP
        PERFORM enqueue(run, 'find_photos', 'find_photos:' || place.id || ':' ||
                        floor(extract(epoch FROM clock_timestamp()) * 1000), '{}', p_city, place.id, NULL, NULL);
        queued := queued + 1;
    END LOOP;
    RETURN queued;
END;
$$;

GRANT EXECUTE ON FUNCTION console_queue_photos(text, bigint, integer) TO psst_platform_console;
