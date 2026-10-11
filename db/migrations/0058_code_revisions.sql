-- A revision made in code (decision 39), cutting what a good mark named or quoting a name its prose already used,
-- keeps the good mark of the revision before it: the reviewer judged the prose, and code changed only what the mark
-- asked for. The tool checks still run on it.
SET search_path = psst, public;

CREATE FUNCTION carry_review(p_token text, p_revision text) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['worker']);
    revision revisions;
    earlier checks;
BEGIN
    SELECT * INTO revision FROM revisions WHERE id = p_revision;
    IF NOT FOUND OR revision.created_by_run <> run.id THEN
        RAISE EXCEPTION 'revision % wasn''t made by this run', p_revision USING ERRCODE = '42501';
    END IF;
    SELECT k.* INTO earlier FROM checks k JOIN revisions r ON r.id = k.revision_id
    WHERE r.item_id = revision.item_id AND r.number = revision.number - 1 AND k.kind = 'review'
      AND k.claim_id IS NULL
    ORDER BY k.id DESC LIMIT 1;
    IF NOT FOUND OR earlier.details ->> 'mark' IS DISTINCT FROM 'good' THEN
        RETURN false;
    END IF;
    -- Recorded as the reviewer's own verdict, carried over: the run that made the revision never checks it.
    PERFORM record_check(earlier.run_id, NULL, p_revision, NULL, 'review', 'pass',
                         'the review''s mark, kept for a revision made in code',
                         earlier.details || jsonb_build_object('carried_from', earlier.revision_id));
    RETURN true;
END;
$$;

GRANT EXECUTE ON FUNCTION carry_review(text, text) TO psst_platform_worker;
