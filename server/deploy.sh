#!/bin/sh
# Deploys the pushed commit to the server: uploads it as a new release, installs dependencies, builds the console,
# runs setup and migrations, switches the release, and restarts the services. Refuses uncommitted or unpushed code.
# Usage: sh server/deploy.sh   (uses the SSH host in PSST_SSH_HOST, default bwh)
set -eu
host="${PSST_SSH_HOST:-bwh}"
base=/www/wwwroot/psst-platform
origin=https://psst-platform.67-230-170-225.sslip.io

[ -z "$(git status --porcelain)" ] || { echo "Commit your changes first; deploys come from pushed commits only." >&2; exit 1; }
git fetch -q origin
[ "$(git rev-parse HEAD)" = "$(git rev-parse '@{u}')" ] || { echo "Push first; deploys come from pushed commits only." >&2; exit 1; }
release=$(git rev-parse --short=12 HEAD)

git archive --format=tar HEAD | ssh "$host" "rm -rf $base/releases/$release && mkdir -p $base/releases/$release && tar -x -C $base/releases/$release"
ssh "$host" "sh -s" <<REMOTE
set -eu
cd $base/releases/$release
echo $release > REVISION
export UV_PYTHON_INSTALL_DIR=$base/python UV_CACHE_DIR=$base/.cache/uv
/root/.local/bin/uv sync -q --no-dev --frozen
(cd web && npm ci --silent --no-audit --no-fund && PSST_CONSOLE_ORIGIN=$origin npm run build -w @psst/console --silent >/dev/null)
sh server/setup.sh
install -d -o psst-platform -g psst-platform work
PSST_CONFIG=$base/env/admin.env .venv/bin/psst db migrate
ln -sfn $base/releases/$release $base/app.next && mv -T $base/app.next $base/app
systemctl enable -q --now psst-platform-fetch psst-platform-system psst-platform-console psst-platform-intake \
  psst-platform-publish.timer psst-platform-backup.timer psst-platform-restore-test.timer
systemctl restart psst-platform-fetch psst-platform-system psst-platform-console psst-platform-intake
ls -1dt $base/releases/* | tail -n +4 | xargs -r rm -rf
echo "deployed $release"
REMOTE
