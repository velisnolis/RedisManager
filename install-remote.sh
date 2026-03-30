#!/bin/bash
# RedisManager — remote installer for CloudLinux + cPanel servers
# Usage: curl -sSL https://raw.githubusercontent.com/velisnolis/RedisManager/main/install-remote.sh | bash
set -euo pipefail

REPO="https://github.com/velisnolis/RedisManager"
BRANCH="main"
TMPDIR=$(mktemp -d)

echo "=== RedisManager Remote Installer ==="
echo ""

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

# Download
echo "Downloading RedisManager from ${REPO}..."
if command -v git &>/dev/null; then
    git clone --depth 1 --branch "$BRANCH" "${REPO}.git" "$TMPDIR/redismanager" 2>/dev/null
else
    # Fallback to tarball if git is not available
    curl -sSL "${REPO}/archive/refs/heads/${BRANCH}.tar.gz" | tar xz -C "$TMPDIR"
    mv "$TMPDIR"/RedisManager-* "$TMPDIR/redismanager"
fi

echo ""

# Run installer
cd "$TMPDIR/redismanager"
bash install.sh

# Cleanup
rm -rf "$TMPDIR"

echo ""
echo "Source: ${REPO}"
