-- The review gate (decision 25). Before the reviewer gates anything it re-marks the golden set blind, in two folds:
-- each fold is marked with the other fold's marks shown as examples, so no story is marked while its mark is in
-- view. Agreement with the editor across both folds must reach gate.min_agreement for the current review prompt,
-- model, golden bar, and golden set, within gate.max_age_days. While it doesn't, reviews and publishing wait.
SET search_path = psst, public;

INSERT INTO task_types (name, runner, description) VALUES
    ('calibrate', 'worker', 'Mark one fold of the golden set blind, to measure the reviewer against the editor.');
INSERT INTO settings (key, value, note) VALUES
    ('gate.min_agreement', '0.9', 'Share of the editor''s marks the reviewer must match before it gates anything.'),
    ('gate.max_age_days', '7', 'Days a calibration stays valid.'),
    ('gate.open', 'false', 'Whether reviews may run and publishing may proceed; set by the system worker.');

CREATE TABLE calibrations (
    id             bigserial PRIMARY KEY,
    task_id        text NOT NULL REFERENCES tasks,
    run_id         text NOT NULL REFERENCES runs,
    model          text NOT NULL,
    prompt_version text NOT NULL,
    bar_version    text,
    golden_version text NOT NULL,
    fold           integer NOT NULL CHECK (fold IN (0, 1)),
    marked         integer NOT NULL CHECK (marked > 0),
    agreed         integer NOT NULL CHECK (agreed BETWEEN 0 AND marked),
    details        jsonb NOT NULL,
    created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE FUNCTION golden_version() RETURNS text
LANGUAGE sql STABLE SET search_path = psst, public, pg_temp AS $$
    SELECT left(md5(coalesce(string_agg(id || ':' || mark, ',' ORDER BY id), '')), 12) FROM golden_stories
$$;

CREATE FUNCTION golden_fold(p_id text) RETURNS integer
LANGUAGE sql IMMUTABLE AS $$ SELECT abs(hashtext(p_id)) % 2 $$;

CREATE OR REPLACE FUNCTION task_model(p_type text, p_input jsonb) RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
    SELECT CASE
        WHEN p_type = 'research_cell' AND (
            SELECT count(*) FROM leads WHERE cell = p_input ->> 'cell' AND status IN ('open', 'later'))
            >= setting('research.dense_leads')::text::integer
        THEN setting('routing.research_cell_dense') #>> '{}'
        WHEN p_type = 'calibrate' THEN setting('routing.review') #>> '{}'
        ELSE (SELECT value #>> '{}' FROM settings WHERE key = 'routing.' || p_type)
    END
$$;

-- Queueing records the model the task is routed to through the same function leasing uses.
CREATE OR REPLACE FUNCTION enqueue(p_run text, p_type text, p_purpose text, p_input jsonb, p_city bigint, p_place text,
                        p_item text, p_revision text, p_exclude text[] DEFAULT '{}', p_independence text DEFAULT NULL,
                        p_priority integer DEFAULT 0) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    task_id text;
    runner text := (SELECT t.runner FROM task_types t WHERE t.name = p_type);
BEGIN
    IF runner IS NULL THEN
        RAISE EXCEPTION 'unknown task type %', p_type USING ERRCODE = '22023';
    END IF;
    INSERT INTO tasks (id, type, purpose, priority, model, city_id, place_id, item_id, revision_id, input,
                       exclude_runs, independence, created_by)
    VALUES (new_id('tk'), p_type, p_purpose, p_priority,
            CASE WHEN runner = 'worker' THEN task_model(p_type, coalesce(p_input, '{}')) END,
            p_city, p_place, p_item, p_revision, coalesce(p_input, '{}'), coalesce(p_exclude, '{}'), p_independence,
            p_run)
    ON CONFLICT (purpose) DO NOTHING
    RETURNING id INTO task_id;
    RETURN coalesce(task_id, (SELECT id FROM tasks WHERE purpose = p_purpose));
END;
$$;

-- Where the gate stands for a review prompt and golden bar: open only when both folds were calibrated for them, the
-- routed model, and the current golden set, recently enough, and together reach the agreement required.
CREATE FUNCTION gate_status(p_prompt text, p_bar text) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    routed text := task_model('review', '{}');
    golden text := golden_version();
    marked integer := 0;
    agreed integer := 0;
    missing integer[] := '{}';
    latest calibrations;
BEGIN
    FOR f IN 0 .. 1 LOOP
        SELECT * INTO latest FROM calibrations c
        WHERE c.fold = f AND c.model = routed AND c.prompt_version = p_prompt
          AND c.bar_version IS NOT DISTINCT FROM p_bar AND c.golden_version = golden
          AND c.created_at > now() - make_interval(days => setting('gate.max_age_days')::text::integer)
        ORDER BY c.created_at DESC LIMIT 1;
        IF FOUND THEN
            marked := marked + latest.marked;
            agreed := agreed + latest.agreed;
        ELSE
            missing := missing || f;
        END IF;
    END LOOP;
    RETURN jsonb_build_object(
        'open', cardinality(missing) = 0 AND marked > 0
                AND agreed::numeric / marked >= setting('gate.min_agreement')::text::numeric,
        'agreement', CASE WHEN marked > 0 THEN round(agreed::numeric / marked, 4) END,
        'missing_folds', to_jsonb(missing), 'model', routed, 'prompt_version', p_prompt, 'bar_version', p_bar,
        'golden_version', golden);
END;
$$;

-- Called by the system worker: records whether the gate is open and queues the calibrations it lacks.
CREATE FUNCTION refresh_gate(p_token text, p_prompt text, p_bar text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['system']);
    status jsonb := gate_status(p_prompt, p_bar);
    f integer;
BEGIN
    UPDATE settings SET value = to_jsonb((status ->> 'open')::boolean) WHERE key = 'gate.open';
    IF NOT EXISTS (SELECT 1 FROM golden_stories) THEN
        RETURN status;
    END IF;
    FOR f IN SELECT value::integer FROM jsonb_array_elements_text(status -> 'missing_folds') LOOP
        PERFORM enqueue(run.id, 'calibrate',
                        concat_ws(':', 'calibrate', status ->> 'golden_version', p_prompt,
                                  coalesce(p_bar, 'none'), status ->> 'model', f),
                        jsonb_build_object('fold', f, 'prompt_version', p_prompt, 'bar_version', p_bar,
                                           'golden_version', status ->> 'golden_version'),
                        NULL, NULL, NULL, NULL, '{}', NULL, 30);
    END LOOP;
    RETURN status;
END;
$$;

-- A calibration result: one mark per golden story in the fold, compared with the editor's.
CREATE FUNCTION submit_calibration(p_token text, p_task text, p_result jsonb, p_prompt text) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['worker']);
    task tasks := held_task(run, p_task);
    fold integer := (task.input ->> 'fold')::integer;
    details jsonb;
    marked integer;
    agreed integer;
BEGIN
    IF task.type <> 'calibrate' THEN
        RAISE EXCEPTION 'task % is not a calibration', p_task USING ERRCODE = '22023';
    END IF;
    IF task.input ->> 'golden_version' IS DISTINCT FROM golden_version() THEN
        RAISE EXCEPTION 'the golden set changed since this calibration was queued' USING ERRCODE = 'P0001';
    END IF;
    IF EXISTS (SELECT 1 FROM golden_stories g WHERE golden_fold(g.id) = fold
               AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(p_result -> 'marks') m WHERE m ->> 'golden' = g.id)) THEN
        RAISE EXCEPTION 'mark every story in the fold' USING ERRCODE = '22023';
    END IF;
    SELECT jsonb_agg(jsonb_build_object('golden', g.id, 'editor', g.mark, 'reviewer', m ->> 'mark',
                                        'reason', m ->> 'reason')),
           count(*), count(*) FILTER (WHERE g.mark = m ->> 'mark')
    INTO details, marked, agreed
    FROM golden_stories g JOIN jsonb_array_elements(p_result -> 'marks') m ON m ->> 'golden' = g.id
    WHERE golden_fold(g.id) = fold;
    INSERT INTO calibrations (task_id, run_id, model, prompt_version, bar_version, golden_version, fold, marked,
                              agreed, details)
    VALUES (task.id, run.id, run.model, task.input ->> 'prompt_version', task.input ->> 'bar_version',
            task.input ->> 'golden_version', fold, marked, agreed, details);
    UPDATE tasks SET state = 'done', result = p_result, prompt = p_prompt, done_by = run.id, done_at = now(),
                     leased_by = NULL, leased_until = NULL
    WHERE id = task.id;
    RETURN jsonb_build_object('fold', fold, 'marked', marked, 'agreed', agreed);
END;
$$;

CREATE OR REPLACE FUNCTION lease_task(p_token text, p_types text[], p_city bigint DEFAULT NULL) RETURNS SETOF tasks
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = psst, public, pg_temp AS $$
DECLARE
    run runs := run_for(p_token, ARRAY['worker', 'system', 'publisher']);
    task tasks;
BEGIN
    PERFORM expire_leases();
    SELECT t.* INTO task FROM tasks t JOIN task_types y ON y.name = t.type
    WHERE t.state = 'queued' AND t.type = ANY(p_types) AND y.active
      AND (p_city IS NULL OR t.city_id = p_city)
      AND y.runner = run.kind
      AND (run.kind <> 'worker' OR task_model(t.type, t.input) = run.model)
      AND NOT run.id = ANY(t.exclude_runs)
      AND (t.place_id IS NULL OR t.type IN ('tool_check', 'resolve_places', 'relink_place')
           OR EXISTS (SELECT 1 FROM places p WHERE p.id = t.place_id AND p.state = 'active'))
      AND (t.type <> 'review' OR setting('gate.open') = 'true'::jsonb)
      AND (t.type <> 'review' OR NOT EXISTS (
            SELECT 1 FROM jsonb_array_elements_text(t.input -> 'revisions') AS r(id)
            JOIN revisions v ON v.id = r.id JOIN items i ON i.id = v.item_id JOIN places p ON p.id = i.place_id
            WHERE p.state = 'pending'))
      AND (t.independence IS NULL OR NOT EXISTS (
            SELECT 1 FROM task_leases l JOIN tasks o ON o.id = l.task_id
            WHERE l.run_id = run.id AND o.independence = t.independence))
    ORDER BY t.priority DESC, t.created_at, t.id
    FOR UPDATE OF t SKIP LOCKED
    LIMIT 1;
    IF NOT FOUND THEN
        RETURN;
    END IF;
    UPDATE tasks SET state = 'leased', leased_by = run.id, model = coalesce(run.model, model),
                     attempts = attempts + 1, problem = NULL,
                     leased_until = now() + make_interval(mins => lease_minutes(type))
    WHERE id = task.id RETURNING * INTO task;
    INSERT INTO task_leases (task_id, run_id) VALUES (task.id, run.id);
    RETURN NEXT task;
END;
$$;

GRANT EXECUTE ON FUNCTION submit_calibration(text, text, jsonb, text) TO psst_platform_worker;
GRANT EXECUTE ON FUNCTION refresh_gate(text, text, text) TO psst_platform_system;
GRANT EXECUTE ON FUNCTION gate_status(text, text), golden_version(), golden_fold(text)
    TO psst_platform_system, psst_platform_console, psst_platform_publisher, psst_platform_worker;
SELECT apply_read_grants();
