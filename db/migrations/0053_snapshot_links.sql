-- A page's links are kept beside its snapshot (decision 34), so a page reused from the cache can still lead to the
-- sources it cites. Snapshots themselves never change, so the links live in a table of their own.
SET search_path = psst, public;

CREATE TABLE snapshot_links (
    snapshot_id text PRIMARY KEY REFERENCES snapshots,
    links       jsonb NOT NULL
);

CREATE FUNCTION record_snapshot_links(p_token text, p_snapshot text, p_links jsonb) RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['system']);
BEGIN
    INSERT INTO snapshot_links (snapshot_id, links) VALUES (p_snapshot, p_links) ON CONFLICT DO NOTHING;
END;
$$;

GRANT EXECUTE ON FUNCTION record_snapshot_links(text, text, jsonb) TO psst_platform_system;
SELECT apply_read_grants();
