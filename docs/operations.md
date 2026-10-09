# Operations

How the platform runs on the server, how to deploy it, and how to recover it.

## On the server

Everything lives under `/www/wwwroot/psst-platform`, beside the previous system and separate from it:

| path | what |
| --- | --- |
| `releases/<commit>`, `app` | deployed code; `app` points at the current release |
| `env/` | one environment file per database role, readable only by what needs it; `secrets.env` holds every password (root only) |
| `public/content`, `public/images` | the published output, served at `https://psst-platform.67-230-170-225.sslip.io/content/` |
| `site/` | the website's static pages |
| `backup/` | nightly dumps and the clone of the private backup repository |

Services (systemd, user `psst-platform`): `psst-platform-fetch` (the fetch service on 127.0.0.1:8471), `psst-platform-system` (the system worker), `psst-platform-console` (the console on 127.0.0.1:4317, at `/admin`), and the timers `psst-platform-publish` (publish and rollback requests from the console, every minute), `psst-platform-backup` (nightly), and `psst-platform-restore-test` (weekly). nginx serves the site from `/etc/nginx/conf.d/psst-platform.conf`.

## Deploying

`sh server/deploy.sh` from a clean, pushed working tree. It uploads the commit as a new release, installs dependencies, builds the console, runs `server/setup.sh` (idempotent), applies migrations, switches `app` to the new release, and restarts the services. The three newest releases are kept; to go back, point `app` at an earlier release and restart the services.

## Working from another machine

Workers and editors reach the database and the fetch service through SSH. Create `~/.config/psst-platform/env` from `.env.example` with `PSST_SSH_HOST` and the worker password from the server's `env/worker.env`. System, publisher, and schema-owner commands run on the server:

```
ssh <host> 'cd /www/wwwroot/psst-platform/app && set -a && . /www/wwwroot/psst-platform/env/system.env && .venv/bin/psst research queue --city london --cells 10'
```

Console accounts: `psst console add-account <name>` with the schema owner's environment (`env/admin.env`); the password is printed once.

## Backups and recovery

- Nightly: a compressed dump in `backup/dumps` (14 days kept), and every table as sorted CSV committed to the private backup repository, which needs a deploy key with write access on the server under the SSH host alias `github-psst-platform-backup`.
- Weekly: the latest dump is restored into a scratch database and checked against the live one.
- Restoring a dump: create an empty `psst_platform` database owned by `psst_platform_admin` with the four extensions (see `server/setup.sh`), then `pg_restore -d psst_platform <dump>` as `postgres`.
- Restoring from the text backup: apply the migrations to an empty database, load each table's CSV files with `COPY ... FROM ... CSV HEADER` in dependency order, then rebuild boundary parts with the query in `psst/places/reference.py`.
