#!/bin/sh
# Nightly backup of the platform database, run as root by psst-platform-backup.timer:
#   1. a compressed custom-format dump, 14 days kept;
#   2. every table as sorted CSV, committed and pushed to the private backup repository.
set -eu
base=/www/wwwroot/psst-platform
dumps="$base/backup/dumps"
repo="$base/backup/repository"
stamp=$(date -u +%Y%m%d)
mkdir -p "$dumps"
sudo -u postgres pg_dump -Fc -d psst_platform -f "/tmp/psst_platform-$stamp.dump"
mv "/tmp/psst_platform-$stamp.dump" "$dumps/psst_platform-$stamp.dump"
chmod 600 "$dumps/psst_platform-$stamp.dump"
find "$dumps" -name 'psst_platform-*.dump' -mtime +14 -delete

cd "$base/app"
PSST_CONFIG="$base/env/admin.env" "$base/app/.venv/bin/psst" db export "$repo/tables" > /dev/null
git -C "$repo" add -A
if ! git -C "$repo" diff --cached --quiet; then
  git -C "$repo" commit -q -m "Backup $stamp"
  git -C "$repo" push -q origin HEAD
fi
echo "$(date -u '+%F %T') backup done"
