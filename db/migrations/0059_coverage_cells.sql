-- Research cells worked to full coverage (decision 40): every lead with an official record gets at least a guide.
SET search_path = psst, public;

INSERT INTO settings (key, value, note) VALUES
    ('harness.coverage_cells', '[]', 'Research cells the harness works to full coverage: every record lead gets a guide, listed houses of one street one place.');
