#!/bin/bash
# RedisManager — installer for CloudLinux + cPanel servers
# Run as root: bash install.sh
set -euo pipefail

INSTALL_DIR="/opt/redismanager"
STATE_DIR="/var/lib/redismanager"
LOG_DIR="/var/log/redismanager"
WHM_CGI="/usr/local/cpanel/whostmgr/docroot/cgi/addon_redismanager.cgi"
APPCONFIG="/var/cpanel/apps/addon_redismanager.conf"
LEGACY_APPCONFIG="/var/cpanel/apps/redismanager.conf"
CRON_FILE="/etc/cron.d/redismanager"

echo "=== RedisManager Installer ==="

# Check prerequisites
if [[ $EUID -ne 0 ]]; then
    echo "ERROR: Must run as root" >&2
    exit 1
fi

if [[ ! -x /opt/alt/redis/bin/redis-server ]]; then
    echo "ERROR: /opt/alt/redis/bin/redis-server not found." >&2
    echo "       Install alt-redis: yum install alt-redis" >&2
    exit 1
fi

if [[ ! -x /usr/local/cpanel/cpanel ]]; then
    echo "ERROR: cPanel not detected" >&2
    exit 1
fi

echo "[1/7] Installing files to ${INSTALL_DIR}..."
mkdir -p "${INSTALL_DIR}"/{bin,etc,templates,hooks,cron}
mkdir -p "$STATE_DIR" "$LOG_DIR"

# Copy files from source directory (same dir as this script)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cp "$SCRIPT_DIR/bin/redismanager-ctl"             "$INSTALL_DIR/bin/"
cp "$SCRIPT_DIR/etc/redismanager.conf"            "$INSTALL_DIR/etc/"
cp "$SCRIPT_DIR/templates/redis-user.conf.tmpl"   "$INSTALL_DIR/templates/"
cp "$SCRIPT_DIR/hooks/redismanager-hooks"         "$INSTALL_DIR/hooks/"
cp "$SCRIPT_DIR/cron/redismanager-healthcheck"    "$INSTALL_DIR/cron/"

chmod +x "$INSTALL_DIR/bin/redismanager-ctl"
chmod +x "$INSTALL_DIR/hooks/redismanager-hooks"
chmod +x "$INSTALL_DIR/cron/redismanager-healthcheck"
chmod 644 "$INSTALL_DIR/etc/redismanager.conf"

# Initialize state file if not present
if [[ ! -f "$STATE_DIR/state.json" ]]; then
    echo '{}' > "$STATE_DIR/state.json"
fi
chmod 644 "$STATE_DIR/state.json"

echo "[2/7] Installing systemd template unit..."
cp "$SCRIPT_DIR/templates/redis-managed.service" "$INSTALL_DIR/templates/"
"$INSTALL_DIR/bin/redismanager-ctl" render-unit

echo "[3/7] Installing WHM plugin..."
cp "$SCRIPT_DIR/whm/addon_redismanager.cgi" "$WHM_CGI"
chmod 700 "$WHM_CGI"
chown root:root "$WHM_CGI"

# Clean up the old appconfig path so WHM only sees one plugin entry.
if [[ -f "$LEGACY_APPCONFIG" ]]; then
    /usr/local/cpanel/bin/unregister_appconfig "$LEGACY_APPCONFIG" 2>/dev/null || true
    rm -f "$LEGACY_APPCONFIG"
fi

cp "$SCRIPT_DIR/whm/redismanager.conf" "$APPCONFIG"
/usr/local/cpanel/bin/register_appconfig "$APPCONFIG"

echo "[4/7] Registering cPanel hooks..."
/usr/local/cpanel/bin/manage_hooks add script "$INSTALL_DIR/hooks/redismanager-hooks" \
    --category Whostmgr --event Accounts::Remove --stage post 2>/dev/null || true
/usr/local/cpanel/bin/manage_hooks add script "$INSTALL_DIR/hooks/redismanager-hooks" \
    --category Whostmgr --event Accounts::suspendacct --stage post 2>/dev/null || true
/usr/local/cpanel/bin/manage_hooks add script "$INSTALL_DIR/hooks/redismanager-hooks" \
    --category Whostmgr --event Accounts::unsuspendacct --stage post 2>/dev/null || true

echo "[5/7] Installing cron healthcheck..."
cat > "$CRON_FILE" <<EOF
# RedisManager health check — every 5 minutes
*/5 * * * * root $INSTALL_DIR/cron/redismanager-healthcheck
EOF

echo "[6/7] Creating convenience symlink..."
ln -sf "$INSTALL_DIR/bin/redismanager-ctl" /usr/local/sbin/redismanager-ctl

echo "[7/7] Verifying installation..."
echo ""
/usr/local/sbin/redismanager-ctl info
echo ""
echo "=== Installation complete ==="
echo ""
echo "Usage:"
echo "  redismanager-ctl enable <username> [memory_mb]"
echo "  redismanager-ctl list"
echo "  WHM > Plugins > Redis Manager"
