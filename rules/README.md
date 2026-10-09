# Rulebook

What content must be, as data. The checks, the CLI, the console, and the task prompts read these files; [docs/content.md](../docs/content.md) explains them in prose and never restates their numbers.

| file | defines |
| --- | --- |
| `writing.yaml` | Words and phrases refused or flagged, US spelling, punctuation |
| `sources.yaml` | Source kinds, what each can support, and the source rules per content type |
| `places.yaml` | Place kinds and sizes, tag types |
| `types/*.yaml` | Each content type: its body schema, length limits, and the checks it goes through |

The rulebook's version is the first 12 hex digits of the SHA-256 of these files, in name order. Every revision records the version it was checked against. Changing a rule is a commit with tests.
