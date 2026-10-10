-- A panel of models can review (decision 29): its run names every member, as vote:<model>+<model>+<model>.
SET search_path = psst, public;

ALTER TABLE runs DROP CONSTRAINT runs_model_check;
ALTER TABLE runs ADD CONSTRAINT runs_model_check
    CHECK (model ~ '^[a-z0-9][a-z0-9.-]*(:[a-z0-9][a-z0-9./_:+-]*)?$');
