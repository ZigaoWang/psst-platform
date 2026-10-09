## Returning your result

- Write the result as JSON that matches `result_schema` in the task file, and nothing else, to a file.
- Submit it: `uv run psst task submit <task file> <result file>`. It checks the result first and tells you what to fix.
- If you can't do the task properly (a source won't load, the task is wrong), give it back with the reason:
  `uv run psst task return <task file> --problem "<what went wrong>"`. Never submit a guess.
- Notes are one or two plain sentences saying what you checked and what you found. US English, no dashes, no
  exclamation marks, no filler.
