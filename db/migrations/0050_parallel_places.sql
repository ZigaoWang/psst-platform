-- How many places of a research cell the harness writes at once (decision 33).
SET search_path = psst, public;

INSERT INTO settings (key, value, note) VALUES
    ('harness.parallel_places', '8', 'Places of one research cell written at the same time.');
