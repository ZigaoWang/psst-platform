-- A second model confirms a featured tier before the story leads the feed (decision 30).
SET search_path = psst, public;

INSERT INTO settings (key, value, note) VALUES
    ('routing.tier_check', '"openrouter:deepseek/deepseek-v4.1-flash"',
     'The second model that confirms a featured tier; never the reviewer itself.');
