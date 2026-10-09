#!/bin/sh
# Server setup for the Psst platform, safe to run again (deploy.sh runs it on every deploy). Run as root from a
# release directory. Creates the service user, directories, database roles and the psst_platform database,
# environment files with generated passwords, systemd units, and the nginx site with its certificate. Nothing
# belonging to the previous system or other sites is changed.
set -eu
base=/www/wwwroot/psst-platform
host=psst-platform.67-230-170-225.sslip.io
here=$(pwd)

id psst-platform >/dev/null 2>&1 || useradd --system --home-dir "$base" --shell /usr/sbin/nologin psst-platform
install -d -m 755 "$base" "$base/releases" "$base/acme" "$base/site"
install -d -m 755 -o psst-platform -g psst-platform "$base/public" "$base/public/content" "$base/public/images"
install -d -m 750 -o root -g psst-platform "$base/env"
install -d -m 700 "$base/backup" "$base/backup/dumps"

# Passwords, generated once.
secrets="$base/env/secrets.env"
if [ ! -s "$secrets" ]; then
  (umask 077; for role in admin system worker publisher console api; do
     printf 'PSST_DB_PASSWORD_%s=%s\n' "$(echo $role | tr a-z A-Z)" "$(openssl rand -hex 24)"
   done > "$secrets")
fi
. "$secrets"

# Roles and database.
cd /tmp
sudo -u postgres psql -q -v ON_ERROR_STOP=1 -f "$here/db/roles.sql"
for role in admin system worker publisher console api; do
  password=$(eval echo "\$PSST_DB_PASSWORD_$(echo $role | tr a-z A-Z)")
  sudo -u postgres psql -q -v ON_ERROR_STOP=1 -c \
    "ALTER ROLE psst_platform_$role WITH LOGIN PASSWORD '$password' CONNECTION LIMIT 40"
done
sudo -u postgres psql -Atc "SELECT 1 FROM pg_database WHERE datname = 'psst_platform'" | grep -q 1 || \
  sudo -u postgres createdb -O psst_platform_admin -E UTF8 -T template0 psst_platform
sudo -u postgres psql -q -v ON_ERROR_STOP=1 -d psst_platform -c "
  CREATE EXTENSION IF NOT EXISTS postgis; CREATE EXTENSION IF NOT EXISTS pg_trgm;
  CREATE EXTENSION IF NOT EXISTS unaccent; CREATE EXTENSION IF NOT EXISTS pgcrypto;
  REVOKE ALL ON DATABASE psst_platform FROM PUBLIC;
  GRANT CONNECT ON DATABASE psst_platform TO psst_platform_admin, psst_platform_system, psst_platform_worker,
    psst_platform_publisher, psst_platform_console, psst_platform_api;"
cd "$here"

# One environment file per role, readable only by what needs it.
common="PSST_DB_HOST=127.0.0.1\nPSST_DB_PORT=5432\nPSST_DB_NAME=psst_platform\n"
write_env() {  # file mode group content
  (umask 077; printf "$4" > "$base/env/$1.tmp")
  chown "root:$3" "$base/env/$1.tmp" && chmod "$2" "$base/env/$1.tmp" && mv "$base/env/$1.tmp" "$base/env/$1"
}
write_env admin.env 600 root "${common}PSST_DB_PASSWORD_ADMIN=$PSST_DB_PASSWORD_ADMIN\n"
write_env worker.env 600 root "${common}PSST_DB_PASSWORD_WORKER=$PSST_DB_PASSWORD_WORKER\n"
write_env system.env 640 psst-platform "${common}PSST_DB_PASSWORD_SYSTEM=$PSST_DB_PASSWORD_SYSTEM\nPSST_IMAGES_DIR=$base/public/images\n"
write_env publisher.env 640 psst-platform "${common}PSST_DB_PASSWORD_PUBLISHER=$PSST_DB_PASSWORD_PUBLISHER\nPSST_PUBLISH_HOST=local\nPSST_PUBLISH_ROOT=$base/public/content\nPSST_PUBLIC_URL=https://$host\n"
write_env console.env 640 psst-platform "PSST_CONSOLE_DATABASE_URL=postgresql://psst_platform_console:$PSST_DB_PASSWORD_CONSOLE@127.0.0.1:5432/psst_platform\n"

# Services and timers.
for unit in psst-platform-fetch.service psst-platform-system.service psst-platform-console.service \
            psst-platform-publish.service psst-platform-publish.timer psst-platform-backup.service \
            psst-platform-backup.timer psst-platform-restore-test.service psst-platform-restore-test.timer; do
  install -m 644 "server/$unit" "/etc/systemd/system/$unit"
done
systemctl daemon-reload

# nginx: a certificate first (served over plain HTTP), then the full site. Each step is tested before reloading.
if [ ! -f /etc/letsencrypt/live/psst-platform/fullchain.pem ]; then
  cat > /etc/nginx/conf.d/psst-platform.conf <<CONF
server {
    listen 80;
    listen [::]:80;
    server_name $host;
    location /.well-known/acme-challenge/ { root $base/acme; }
}
CONF
  nginx -t -q && systemctl reload nginx
  certbot certonly --webroot -w "$base/acme" --cert-name psst-platform -d "$host" --non-interactive --agree-tos \
    --register-unsafely-without-email --keep-until-expiring
fi
install -m 644 server/nginx.conf /etc/nginx/conf.d/psst-platform.conf
nginx -t -q && systemctl reload nginx

# The backup repository, if its deploy key is in place (see docs/operations.md).
if [ ! -d "$base/backup/repository/.git" ] && ssh -o BatchMode=yes -T github-psst-platform-backup 2>&1 | grep -q "successfully"; then
  git clone -q github-psst-platform-backup:ZigaoWang/psst-platform-backup.git "$base/backup/repository"
  git -C "$base/backup/repository" config user.name "Psst platform backup"
  git -C "$base/backup/repository" config user.email "backup@psst-platform.invalid"
fi
echo "setup done"
