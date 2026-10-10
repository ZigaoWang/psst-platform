-- Leads can come from an official record (decision 34): every item in a cell carrying a heritage list entry.
SET search_path = psst, public;

ALTER TABLE leads DROP CONSTRAINT leads_origin_check;
ALTER TABLE leads ADD CONSTRAINT leads_origin_check CHECK (origin IN ('wikipedia', 'osm', 'wikidata', 'legacy', 'record'));
