-- The writing step of research can use its own model (decision 32): writing needs craft rather than tools.
SET search_path = psst, public;

INSERT INTO settings (key, value, note) VALUES
    ('routing.research_writer', '"openrouter:z-ai/glm-5.3"',
     'Model for the writing step of research; null to use the model that gathered the evidence.');
