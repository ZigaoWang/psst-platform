-- Queueing a calibration again brings back one that was cancelled or failed, instead of skipping it.
SET search_path = psst, public;

CREATE OR REPLACE FUNCTION queue_calibration(p_token text, p_model text, p_prompt text, p_bar text) RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['system']);
    golden text := golden_version();
    queued integer := 0;
BEGIN
    FOR f IN 0 .. 1 LOOP
        -- A calibration cancelled or failed earlier is queued again rather than skipped as a duplicate.
        UPDATE tasks SET state = 'queued', attempts = 0, problem = NULL
        WHERE purpose = concat_ws(':', 'calibrate', golden, p_prompt, coalesce(p_bar, 'none'), p_model, f)
          AND state IN ('cancelled', 'failed');
        IF FOUND THEN
            queued := queued + 1;
        ELSIF enqueue(run.id, 'calibrate', concat_ws(':', 'calibrate', golden, p_prompt, coalesce(p_bar, 'none'), p_model, f),
                   jsonb_build_object('fold', f, 'model', p_model, 'prompt_version', p_prompt, 'bar_version', p_bar,
                                      'golden_version', golden),
                   NULL, NULL, NULL, NULL, '{}', NULL, 30) IS NOT NULL THEN
            queued := queued + 1;
        END IF;
    END LOOP;
    RETURN queued;
END;
$$;
