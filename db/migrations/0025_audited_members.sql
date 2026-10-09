-- A revision that was itself audited and passed is audited, whatever the rest of its batch did. A failed batch sends
-- back the revisions the audit found wrong and rechecks only the ones it never looked at; it no longer rechecks
-- revisions the audit read in full and passed. Revisions already sent back that way return to accepted.
SET search_path = psst, public;

CREATE OR REPLACE FUNCTION settle_audit(p_run text, p_batch text) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    batch audit_batches;
    member record;
    found_errors integer;
BEGIN
    SELECT * INTO batch FROM audit_batches WHERE id = p_batch FOR UPDATE;
    IF batch.outcome <> 'open' OR EXISTS (
        SELECT 1 FROM tasks WHERE type = 'audit' AND input ->> 'batch' = p_batch AND state <> 'done') THEN
        RETURN batch.outcome;
    END IF;
    UPDATE audit_members m SET error = EXISTS (
        SELECT 1 FROM checks k WHERE k.revision_id = m.revision_id AND k.kind = 'audit'
          AND k.created_at >= batch.created_at AND k.verdict NOT IN ('supported', 'pass'))
    WHERE m.batch_id = p_batch AND m.sampled;
    SELECT count(*) INTO found_errors FROM audit_members WHERE batch_id = p_batch AND error;
    UPDATE audit_batches
    SET errors = found_errors, rate = found_errors::numeric / sample_size, settled_at = now(),
        outcome = CASE WHEN found_errors::numeric / sample_size <= threshold THEN 'passed' ELSE 'failed' END
    WHERE id = p_batch RETURNING * INTO batch;
    IF batch.outcome = 'failed' THEN
        FOR member IN
            SELECT m.revision_id, m.error, i.id AS item_id, i.city_id, i.place_id, i.current_revision
            FROM audit_members m JOIN revisions r ON r.id = m.revision_id JOIN items i ON i.id = r.item_id
            WHERE m.batch_id = p_batch AND i.state = 'accepted' AND i.current_revision = m.revision_id
              AND (m.error OR NOT m.sampled)
        LOOP
            IF member.error THEN
                PERFORM transition(member.item_id, 'draft', p_run, NULL, 'the audit found an error');
                PERFORM enqueue(p_run, 'revise', 'revise:audit:' || p_batch || ':' || member.revision_id,
                                jsonb_build_object('problems', (
                                    SELECT jsonb_agg(note) FROM checks WHERE revision_id = member.revision_id
                                      AND kind = 'audit' AND verdict NOT IN ('supported', 'pass'))),
                                member.city_id, member.place_id, member.item_id, member.revision_id, '{}', NULL, 5);
            ELSE
                PERFORM transition(member.item_id, 'checking', p_run, NULL,
                                   'its audit batch failed, so it is checked again');
                PERFORM advance(p_run, member.revision_id);
            END IF;
        END LOOP;
    END IF;
    RETURN batch.outcome;
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
      AND (b.outcome = 'passed' OR (b.outcome = 'failed' AND m.sampled AND NOT m.error)) LIMIT 1
) audited ON true
WHERE i.state <> 'retired' AND (audited.passed OR i.published_revision IS NOT NULL);

-- Accepted work that can't publish yet, and why.
CREATE OR REPLACE VIEW held_back AS
SELECT i.id AS item_id, i.type, i.place_id, i.city_id, i.current_revision AS revision_id,
       CASE WHEN EXISTS (SELECT 1 FROM audit_members m JOIN audit_batches b ON b.id = m.batch_id
                         WHERE m.revision_id = i.current_revision AND b.outcome = 'open')
            THEN 'its audit batch is still open'
            ELSE 'waiting to be audited' END AS reason
FROM items i
WHERE i.state = 'accepted' AND NOT EXISTS (
    SELECT 1 FROM audit_members m JOIN audit_batches b ON b.id = m.batch_id
    WHERE m.revision_id = i.current_revision
      AND (b.outcome = 'passed' OR (b.outcome = 'failed' AND m.sampled AND NOT m.error)));

-- Revisions a failed batch sent back to checking although their own audit passed.
DO $$
DECLARE
    member record;
    system_run text := new_id('ru');
BEGIN
    INSERT INTO runs (id, kind, operator, token_hash, notes, ended_at)
    VALUES (system_run, 'system', 'schema migration', gen_random_bytes(32), 'migration 0025: audited revisions', now());
    FOR member IN
        SELECT i.id AS item_id FROM items i
        JOIN audit_members m ON m.revision_id = i.current_revision
        JOIN audit_batches b ON b.id = m.batch_id
        WHERE i.state = 'checking' AND b.outcome = 'failed' AND m.sampled AND NOT m.error
          AND (SELECT t.reason FROM transitions t WHERE t.item_id = i.id ORDER BY t.id DESC LIMIT 1)
              = 'its audit batch failed, so it is checked again'
    LOOP
        PERFORM transition(member.item_id, 'accepted', system_run, NULL, 'its own audit passed');
    END LOOP;
END;
$$;
