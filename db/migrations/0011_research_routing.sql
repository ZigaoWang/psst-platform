-- New databases route research to Haiku 5.5 (decisions.md, 19). Existing ones change it in the console, where the
-- change is kept with its reason; this only sets the starting value where nobody has changed it yet.
SET search_path = psst, public;
UPDATE settings SET value = '"claude-haiku-5-5"'
WHERE key = 'routing.research_cell' AND updated_by IS NULL AND value = '"claude-sonnet-5-5"';
