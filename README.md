# RedisManager for cPanel/WHM

<p align="center">
  <img src="whm/redismanager-icon.svg" width="80" alt="RedisManager icon">
</p>

**RedisManager** is a lightweight WHM plugin that provides per-user isolated Redis instances on CloudLinux Shared PRO servers with cPanel. It reuses the Redis binary shipped by CloudLinux's AccelerateWP (`alt-redis`) and applies the same socket-based isolation model — but for **any CMS**, not just WordPress.

Built primarily for **Joomla** sites that can't use AccelerateWP, but works for any application that supports Redis via Unix sockets.

<p align="center">
  <img src="docs/screenshot.png" alt="RedisManager WHM interface" width="800">
</p>

## What it does

- Creates **isolated Redis instances per cPanel user**, each running under the user's UID inside CageFS
- Uses **Unix sockets** (no TCP ports exposed) with `600` permissions — users can only access their own Redis
- Integrates with **CloudLinux LVE limits** — Redis memory and CPU count towards the user's resource allocation
- Provides a **WHM admin interface** (Plugins → Redis Manager) to enable/disable Redis per account
- Includes **cPanel hooks** for automatic cleanup on account deletion/suspension
- Runs a **health check cron** every 5 minutes to restart failed instances
- Enforces a **global memory budget** (default: 2 GB) to prevent overcommitting server RAM

## What it does NOT do

- **Does not install its own Redis binary.** It depends on `alt-redis`, the Redis package shipped by CloudLinux as part of AccelerateWP. If `alt-redis` is not installed, RedisManager will refuse to enable instances.
- **Does not interfere with AccelerateWP.** WordPress sites managed by AccelerateWP continue to work as before. RedisManager uses a separate directory (`~/.redis-managed/`) and AccelerateWP's monitoring daemon ignores our instances (verified by code inspection of `clwpos_monitoring`).
- **Does not configure your CMS automatically.** After enabling Redis for a user, you must manually configure the CMS (Joomla, Drupal, etc.) to use the Redis socket. Instructions are shown in the WHM interface.
- **Does not provide Redis Cluster, Sentinel, or replication.** Each instance is a standalone, single-node Redis server running in cache-only mode (no persistence).
- **Does not manage AccelerateWP instances.** WordPress Redis managed by AccelerateWP is completely separate and should be managed through CloudLinux's own tools.

## Requirements

- **CloudLinux Shared PRO** v8.x or v9.x with CageFS enabled
- **cPanel/WHM** 110+ (tested on 134.0.x)
- **alt-redis** package installed (comes with AccelerateWP / CloudLinux Shared PRO)
- Root access to the server

## Compatibility

- **Redis → Valkey migration:** CloudLinux may migrate from Redis to Valkey (the open-source Redis fork). This is fully compatible — same protocol, same config format. Only the binary path changes, which is configurable in `etc/redismanager.conf`.

## Installation

### Quick install (one-liner)

```bash
curl -sSL https://raw.githubusercontent.com/velisnolis/RedisManager/main/install-remote.sh | bash
```

### Manual install

1. Clone the repository:

```bash
git clone https://github.com/velisnolis/RedisManager.git /tmp/redismanager
```

2. Run the installer as root:

```bash
cd /tmp/redismanager
bash install.sh
```

The installer will:
- Copy files to `/opt/redismanager/`
- Install the systemd template unit (`redis-managed@.service`)
- Register the WHM plugin and icon
- Register cPanel hooks for account lifecycle events
- Set up the health check cron job
- Create a convenience symlink at `/usr/local/sbin/redismanager-ctl`

3. Verify:

```bash
redismanager-ctl info
```

## Uninstallation

```bash
cd /tmp/redismanager   # or wherever the source is
bash uninstall.sh
```

This will stop all managed Redis instances, remove user data directories, unregister the WHM plugin and hooks, and clean up all installed files. Logs are preserved at `/var/log/redismanager/`.

## Usage

### WHM Interface

Go to **WHM → Plugins → Redis Manager**. From there you can:

- **Enable** Redis for any cPanel account (set memory limit in MB)
- **Disable** Redis (stops the instance and removes data)
- **Restart** a running instance
- **Flush** all cached data
- **Set memory** limit for an existing instance

Each enabled account shows the socket path and Joomla configuration instructions.

### Command Line

```bash
# Enable Redis for a user (default 64MB)
redismanager-ctl enable <username> [memory_mb]

# Disable Redis
redismanager-ctl disable <username>

# Check status
redismanager-ctl status <username>

# List all managed instances
redismanager-ctl list

# Restart an instance
redismanager-ctl restart <username>

# Flush all data
redismanager-ctl flush <username>

# Change memory limit
redismanager-ctl set-memory <username> <mb>

# Change max client connections (default 128, range 8-1024)
redismanager-ctl set-maxclients <username> <n>

# Show global info (binary version, memory budget, etc.)
redismanager-ctl info
```

## CMS Configuration

### Joomla 4/5

After enabling Redis for a user, configure Joomla at **System → Global Configuration → System**:

| Setting | Value |
|---|---|
| Cache Handler | `Redis` |
| Redis Server Host | `/home/<username>/.redis-managed/redis.sock` |
| Redis Server Port | `6379` *(default — ignored when using a socket, but Joomla requires a valid port number)* |
| Redis Server Database | `0` |

For sessions (**System → Global Configuration → System → Session**):

| Setting | Value |
|---|---|
| Session Handler | `Redis` |
| Redis Server Host | `/home/<username>/.redis-managed/redis.sock` |
| Redis Server Port | `6379` |
| Redis Server Database | `1` *(separate DB from cache)* |

### PHP Session Locking (automatic)

When Redis is used as a session handler, PHP's `phpredis` extension requires session locking to prevent race conditions. Without it, concurrent AJAX requests (common in Joomla admin) can corrupt session data, causing random 500 errors and "poltergeist" behavior.

RedisManager **automatically deploys** a `.user.ini` file to all document roots when enabling Redis for a user:

```ini
redis.session.locking_enabled = 1
redis.session.lock_retries = 300
redis.session.lock_wait_time = 10000
```

This is removed automatically when Redis is disabled. If you add new domains to the account after enabling Redis, run `redismanager-ctl disable <user>` followed by `redismanager-ctl enable <user>` to redeploy the session locking config to all document roots.

### Other CMS / Frameworks

Any application that supports Redis via Unix sockets can use the managed instance. The connection details are always:

- **Socket:** `/home/<username>/.redis-managed/redis.sock`
- **Port:** not applicable (socket connection)
- **Password:** none
- **Databases:** 0 and 1 available (2 databases configured by default)

## Architecture

```
/opt/redismanager/
├── bin/redismanager-ctl              # Control script
├── etc/redismanager.conf             # Global config (binary path, budget, etc.)
├── templates/
│   ├── redis-managed.service         # Systemd template unit
│   └── redis-user.conf.tmpl          # Per-user Redis config template
├── hooks/redismanager-hooks          # cPanel lifecycle hooks
└── cron/redismanager-healthcheck     # Health check (runs every 5 min)

/usr/local/cpanel/whostmgr/docroot/
├── cgi/addon_redismanager.cgi        # WHM admin interface (Perl CGI)
└── addon_plugins/redismanager-icon.svg  # Plugin icon

/etc/systemd/system/
└── redis-managed@.service            # Systemd template (one instance per user)

/var/lib/redismanager/state.json      # Enabled users and their config
/var/log/redismanager/                # Plugin and health check logs

Per user:
/home/<user>/.redis-managed/
├── redis.conf                        # Auto-generated Redis config
├── redis.sock                        # Unix socket (permissions 600)
├── redis.pid                         # PID file
└── redis.log                         # Instance log
```

### How isolation works

Each Redis instance is launched via `cagefs_enter.proxied` under the user's UID, the same mechanism AccelerateWP uses. This means:

- The Redis process runs **inside CageFS** with the user's filesystem view
- **LVE limits apply** — memory and CPU count towards the user's CloudLinux resource allocation
- The socket has **600 permissions** — only the owning user can connect
- **AccelerateWP's monitoring daemon** (`clwpos_monitoring`) ignores our instances because it specifically looks for processes with `.clwpos/redis.sock` in their command line

### Coexistence with AccelerateWP

| | AccelerateWP (WordPress) | RedisManager |
|---|---|---|
| Directory | `~/.clwpos/` | `~/.redis-managed/` |
| Socket | `~/.clwpos/redis.sock` | `~/.redis-managed/redis.sock` |
| Manager | `clwpos_monitoring` daemon | systemd + cron health check |
| Binary | `/opt/alt/redis/bin/redis-server` | Same binary |

A user can have **both** an AccelerateWP Redis instance (for WordPress) and a RedisManager instance (for Joomla or other CMS) running simultaneously without conflicts.

## Configuration

Global settings are in `/opt/redismanager/etc/redismanager.conf`:

| Setting | Default | Description |
|---|---|---|
| `REDIS_BINARY` | `/opt/alt/redis/bin/redis-server` | Path to Redis/Valkey binary |
| `DEFAULT_MEMORY_MB` | `64` | Default maxmemory per instance |
| `DEFAULT_MAXCLIENTS` | `128` | Default max connections per instance |
| `TOTAL_BUDGET_MB` | `2048` | Total memory budget across all instances |
| `USE_CAGEFS` | `true` | Launch Redis inside CageFS |

## Disclaimer

**This software is provided "as is", without warranty of any kind, express or implied.** Use at your own risk.

- RedisManager depends on CloudLinux's `alt-redis` package, which is an internal component of AccelerateWP. CloudLinux may change, move, or remove this binary at any time without notice. If this happens, update the `REDIS_BINARY` path in the configuration or install Redis from an alternative source (e.g., Remi repository).
- RedisManager is **not affiliated with, endorsed by, or supported by** cPanel LLC, CloudLinux Inc., or Redis Ltd.
- The authors are **not responsible** for any data loss, downtime, or other issues arising from the use of this software.
- **Always make a server snapshot before installing** any third-party WHM plugin.
- Test thoroughly in a staging environment before deploying to production.

## License

MIT License — see [LICENSE](LICENSE) for details.
