-- Leads the sweep can tell are not places (a company, a person, a constituency) are recorded as skipped by the
-- system with the reason, so every lead stays accounted for and none reaches a researcher.
SET search_path = psst, public;

CREATE OR REPLACE FUNCTION record_leads(p_token text, p_cell text, p_leads jsonb) RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    system runs := run_for(p_token, ARRAY['system']);
    lead jsonb;
    known text;
    new_status text;
    recorded integer := 0;
BEGIN
    FOR lead IN SELECT value FROM jsonb_array_elements(p_leads) LOOP
        SELECT id INTO known FROM places WHERE state = 'active'
          AND ((lead ->> 'wikidata' IS NOT NULL AND wikidata_id = lead ->> 'wikidata')
               OR (lead ->> 'osm' IS NOT NULL AND osm_ref = lead ->> 'osm')) LIMIT 1;
        new_status := CASE WHEN known IS NOT NULL THEN 'known' WHEN lead ? 'skip' THEN 'skipped' ELSE 'open' END;
        INSERT INTO leads (id, cell, key, origin, name, wikidata_id, osm_ref, url, what, fame, legacy_place, status,
                           reason, place_id, decided_by, decided_at)
        VALUES (new_id('ld'), p_cell, lead ->> 'key', lead ->> 'origin', lead ->> 'name', lead ->> 'wikidata',
                lead ->> 'osm', lead ->> 'url', lead ->> 'what', (lead ->> 'fame')::integer, lead ->> 'legacy',
                new_status, CASE WHEN new_status = 'skipped' THEN lead ->> 'skip' END, known,
                CASE WHEN new_status <> 'open' THEN system.id END, CASE WHEN new_status <> 'open' THEN now() END)
        ON CONFLICT (cell, key) DO UPDATE SET name = EXCLUDED.name, url = coalesce(EXCLUDED.url, leads.url),
            what = coalesce(EXCLUDED.what, leads.what), fame = coalesce(EXCLUDED.fame, leads.fame),
            status = CASE WHEN leads.status = 'open' AND EXCLUDED.status = 'skipped' THEN 'skipped' ELSE leads.status END,
            reason = CASE WHEN leads.status = 'open' AND EXCLUDED.status = 'skipped' THEN EXCLUDED.reason
                          ELSE leads.reason END,
            decided_by = CASE WHEN leads.status = 'open' AND EXCLUDED.status = 'skipped' THEN EXCLUDED.decided_by
                              ELSE leads.decided_by END,
            decided_at = CASE WHEN leads.status = 'open' AND EXCLUDED.status = 'skipped' THEN EXCLUDED.decided_at
                              ELSE leads.decided_at END;
        recorded := recorded + 1;
    END LOOP;
    RETURN recorded;
END;
$$;
