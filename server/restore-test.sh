#!/bin/sh
# Weekly: restore the latest dump into a scratch database and check it. Run as root by
# psst-platform-restore-test.timer; exits non-zero when the restore reports errors, a table is missing, or a table
# holds more rows than the live one (rows only accumulate, so a restored table can't be larger).
set -eu
base=/www/wwwroot/psst-platform
latest=$(ls -1 "$base/backup/dumps"/psst_platform-*.dump | tail -1)
scratch=psst_platform_restore_test
cd /tmp
sudo -u postgres dropdb --if-exists "$scratch"
sudo -u postgres createdb -O psst_platform_admin "$scratch"
if ! sudo -u postgres pg_restore -d "$scratch" --exit-on-error "$latest"; then
  sudo -u postgres dropdb "$scratch"
  echo "restore of $latest failed" >&2
  exit 1
fi
counts() {
  for table in $(sudo -u postgres psql -At -d psst_platform -c "SELECT tablename FROM pg_tables WHERE schemaname = 'psst' ORDER BY 1"); do
    printf '%s %s\n' "$table" "$(sudo -u postgres psql -At -d "$1" -c "SELECT count(*) FROM psst.$table" 2>/dev/null || echo missing)"
  done
}
counts psst_platform > /tmp/psst-platform-live.counts
counts "$scratch" > /tmp/psst-platform-restored.counts
sudo -u postgres dropdb "$scratch"
awk 'NR == FNR { live[$1] = $2; next }
     $2 == "missing" || $2 + 0 > live[$1] + 0 { print "mismatch: " $1 " restored " $2 ", live " live[$1]; bad = 1 }
     END { exit bad }' /tmp/psst-platform-live.counts /tmp/psst-platform-restored.counts
echo "$(date -u '+%F %T') restore test passed with $latest"
