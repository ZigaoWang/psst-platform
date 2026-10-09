#!/bin/sh
# Rebuilds the website when production holds a content version the site wasn't built from, then swaps the new
# pages in all at once. Run as root by psst-platform-site.timer, and by deploy.sh after each deploy.
set -eu
base=/www/wwwroot/psst-platform
content="$base/public/content/production/v2"
[ -f "$content/manifest.json" ] || { echo "nothing published yet"; exit 0; }
version=$(sed -n 's/.*"contentVersion": *"\([^"]*\)".*/\1/p' "$content/manifest.json")
release=$(readlink -f "$base/app")
if [ "${1:-}" != "--force" ] && [ -f "$base/site/.version" ] && [ "$(cat "$base/site/.version")" = "$version $release" ]; then
  exit 0
fi
cd "$release/web/site"
rm -rf build
PSST_CONTENT_SOURCE="$content" npm run build --silent > /tmp/psst-platform-site-build.log 2>&1 || {
  cat /tmp/psst-platform-site-build.log >&2; exit 1; }
echo "$version $release" > build/.version
rm -rf "$base/site.next" && mv build "$base/site.next"
mv -T "$base/site" "$base/site.previous" 2>/dev/null || true
mv -T "$base/site.next" "$base/site"
rm -rf "$base/site.previous"
echo "$(date -u '+%F %T') site built from $version"
