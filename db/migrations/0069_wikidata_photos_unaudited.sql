-- A place's own Wikidata image publishes once accepted, with no model audit (decision 46): the auditor reads text,
-- and the image's license and credit come from Commons in code. Audit planning leaves these photos out, and audits
-- already queued for them are cancelled.
SET search_path = psst, public;

CREATE FUNCTION wikidata_photo(p_revision text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
    SELECT coalesce(reason = 'the place''s own Wikidata image', false) FROM revisions WHERE id = p_revision
$$;

CREATE OR REPLACE FUNCTION plan_audits(p_token text, p_force boolean DEFAULT false) RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['system', 'editor']);
    review record;
    grp record;
    member record;
    batch_id text;
    sample integer;
    planned integer := 0;
BEGIN
    FOR review IN
        SELECT t.id FROM tasks t WHERE t.type = 'review' AND t.state = 'done'
          AND NOT EXISTS (SELECT 1 FROM audit_batches b WHERE b.review_task = t.id)
    LOOP
        IF plan_review_audit(run.id, review.id) IS NOT NULL THEN
            planned := planned + 1;
        END IF;
    END LOOP;
    FOR grp IN
        SELECT i.type, i.city_id, array_agg(i.current_revision ORDER BY random()) AS members
        FROM items i
        WHERE i.type IN ('translation', 'photo') AND i.state = 'accepted'
          AND NOT EXISTS (SELECT 1 FROM audit_members m WHERE m.revision_id = i.current_revision)
          AND NOT wikidata_photo(i.current_revision)
        GROUP BY i.type, i.city_id
        HAVING count(*) >= 10 OR p_force
    LOOP
        batch_id := new_id('ab');
        sample := greatest(1, ceil(cardinality(grp.members) * setting('audit.sample_rate')::text::numeric))::integer;
        INSERT INTO audit_batches (id, type, city_id, size, sample_size, threshold, created_by)
        VALUES (batch_id, grp.type, grp.city_id, cardinality(grp.members), sample, 0, run.id);
        FOR member IN SELECT m.id, m.n FROM unnest(grp.members) WITH ORDINALITY AS m(id, n) LOOP
            INSERT INTO audit_members (batch_id, revision_id, sampled) VALUES (batch_id, member.id, member.n <= sample);
            IF member.n <= sample THEN
                PERFORM enqueue(run.id, 'audit', 'audit:' || batch_id || ':' || member.id,
                                jsonb_build_object('batch', batch_id), grp.city_id,
                                (SELECT i.place_id FROM items i JOIN revisions r ON r.item_id = i.id WHERE r.id = member.id),
                                (SELECT item_id FROM revisions WHERE id = member.id), member.id,
                                ARRAY[(SELECT created_by_run FROM revisions WHERE id = member.id)], NULL, 5);
            END IF;
        END LOOP;
        planned := planned + 1;
    END LOOP;
    RETURN planned;
END;
$$;

CREATE OR REPLACE VIEW publishable AS
SELECT i.id AS item_id, i.type, i.place_id, i.city_id, i.translates, i.language, i.position,
       CASE WHEN audited.passed THEN i.current_revision ELSE i.published_revision END AS revision_id,
       coalesce(audited.passed, false) AND i.current_revision IS DISTINCT FROM i.published_revision AS is_new
FROM items i
LEFT JOIN LATERAL (
    SELECT true AS passed FROM audit_members m JOIN audit_batches b ON b.id = m.batch_id
    WHERE i.state = 'accepted' AND m.revision_id = i.current_revision
      AND (b.outcome = 'passed' OR (b.outcome = 'failed' AND m.sampled AND NOT m.error))
    UNION ALL
    SELECT true WHERE i.state = 'accepted' AND wikidata_photo(i.current_revision)
    LIMIT 1
) audited ON true
WHERE i.state <> 'retired' AND (audited.passed OR i.published_revision IS NOT NULL);

UPDATE tasks SET state = 'cancelled', problem = 'a place''s own Wikidata image publishes without a model audit'
WHERE type = 'audit' AND state = 'queued' AND wikidata_photo(revision_id);

GRANT EXECUTE ON FUNCTION wikidata_photo(text) TO psst_platform_worker, psst_platform_system, psst_platform_publisher,
    psst_platform_console, psst_platform_api;
SELECT apply_read_grants();
