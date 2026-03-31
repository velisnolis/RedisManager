#!/bin/bash
# RedisManager — uninstaller
# Run as root: bash uninstall.sh
set -euo pipefail

INSTALL_DIR="/opt/redismanager"
STATE_DIR="/var/lib/redismanager"
SYSTEMD_UNIT="/etc/systemd/system/redis-managed@.service"
WHM_CGI="/usr/local/cpanel/whostmgr/docroot/cgi/addon_redismanager.cgi"
APPCONFIG="/var/cpanel/apps/addon_redismanager.conf"
LEGACY_APPCONFIG="/var/cpanel/apps/redismanager.conf"
CRON_FILE="/etc/cron.d/redismanager"

echo "=== RedisManager Uninstaller ==="

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: Must run as root" >&2
    exit 1
fi

echo ""
echo "WARNING: This will:"
echo "  - Stop and disable ALL managed Redis instances"
echo "  - Remove the WHM plugin"
echo "  - Remove cPanel hooks"
echo "  - Remove all plugin files"
echo ""
echo "User data in ~/.redis-managed/ will also be removed."
echo ""
read -p "Continue? (yes/no): " CONFIRM
if [[ "$CONFIRM" != "yes" ]]; then
    echo "Aborted."
    exit 0
fi

echo "[1/6] Stopping all managed Redis instances..."
if [[ -f "$STATE_DIR/state.json" ]]; then
    python3 -c "
import json
with open('$STATE_DIR/state.json') as f:
    state = json.load(f)
for user in state:
    print(user)
" 2>/dev/null | while read -r user; do
        echo "  Disabling Redis for ${user}..."
        if [[ -x "$INSTALL_DIR/bin/redismanager-ctl" ]]; then
            "$INSTALL_DIR/bin/redismanager-ctl" disable "$user" 2>/dev/null || true
        else
            systemctl stop "redis-managed@${user}" 2>/dev/null || true
            systemctl disable "redis-managed@${user}" 2>/dev/null || true
            rm -rf "/home/${user}/.redis-managed" 2>/dev/null || true
        fi
    done
fi

echo "[2/6] Removing systemd template..."
rm -f "$SYSTEMD_UNIT"
systemctl daemon-reload

echo "[3/6] Removing WHM plugin..."
rm -f "$WHM_CGI"
if [[ -f "$APPCONFIG" ]]; then
    /usr/local/cpanel/bin/unregister_appconfig "$APPCONFIG" 2>/dev/null || true
    rm -f "$APPCONFIG"
fi
if [[ -f "$LEGACY_APPCONFIG" ]]; then
    /usr/local/cpanel/bin/unregister_appconfig "$LEGACY_APPCONFIG" 2>/dev/null || true
    rm -f "$LEGACY_APPCONFIG"
fi

echo "[4/6] Removing cPanel hooks..."
/usr/local/cpanel/bin/manage_hooks delete script "$INSTALL_DIR/hooks/redismanager-hooks" 2>/dev/null || true

echo "[5/6] Removing cron and symlink..."
rm -f "$CRON_FILE"
rm -f /usr/local/sbin/redismanager-ctl

echo "[6/6] Removing plugin files..."
rm -rf "$INSTALL_DIR"
rm -rf "$STATE_DIR"
# Keep logs for reference
echo "  (logs preserved at /var/log/redismanager/)"

echo ""
echo "=== Uninstallation complete ==="
