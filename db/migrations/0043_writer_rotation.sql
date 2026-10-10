-- The writing bake-off (decision 29): a research cell can rotate its writers, one model per place, and each writing
-- call is tied to the place it produced, so every place's review marks, audit result, and cost belong to one model.
SET search_path = psst, public;

ALTER TABLE runs DROP CONSTRAINT runs_model_check;
ALTER TABLE runs ADD CONSTRAINT runs_model_check
    CHECK (model ~ '^[a-z0-9][a-z0-9.-]*(:[a-z0-9][a-z0-9./_:+-]*)?$');
ALTER TABLE harness_calls ADD COLUMN place_id text REFERENCES places;

CREATE FUNCTION tie_harness_calls(p_token text, p_calls bigint[], p_place text) RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['worker']);
BEGIN
    UPDATE harness_calls SET place_id = p_place WHERE id = ANY(p_calls) AND run_id = run.id;
END;
$$;

GRANT EXECUTE ON FUNCTION tie_harness_calls(text, bigint[], text) TO psst_platform_worker;
