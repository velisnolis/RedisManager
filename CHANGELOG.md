# Changelog

## 2026-04-07

### Fixed

- Restored compatibility between `redismanager-ctl launch` and the production systemd unit, which runs managed Redis instances as the cPanel account user instead of `root`.
- Reopened runtime permissions required by the non-root launch path for the control script, state file, and runtime directories.
- Normalized `.user.ini` session-locking management so legacy unmarked entries do not accumulate alongside the newer marked block format.

### Operational notes

- A production incident after the 2026-04-06 hardening deploy caused temporary `500` errors on sites backed by managed Redis instances.
- The root cause and recovery steps are recorded in [docs/POSTMORTEM-2026-04-07-runtime-permissions.md](docs/POSTMORTEM-2026-04-07-runtime-permissions.md).

## 2026-04-06

### Changed

- Hardened `redismanager-ctl` so state parsing no longer relies on `eval`, and restricted the CLI to `root`.
- Serialized budget-sensitive operations and made config writes atomic in both the CLI and WHM config save flow.
- Refused unsafe writes through symlinks or paths outside `/home/$user` when managing Redis config, `.user.ini`, and Joomla fallback rewrites.
- Tightened install-time permissions for state, logs, and runtime scripts, and added a `logrotate` policy for RedisManager logs.
- Added restart throttling to the healthcheck cron so a flapping instance is not restarted forever.

### Validated

- Local shell syntax checks passed for `redismanager-ctl`, `redismanager-healthcheck`, `redismanager-hooks`, `install.sh`, and `uninstall.sh`.
- Production validation on `server.miras.pro` passed after targeted deploy, including WHM CGI syntax, `redismanager-ctl info/list/status`, manual healthcheck execution, and verification that all managed Redis instances remained active.

## 2026-04-05

### Changed

- RedisManager now supports CloudLinux site isolation accounts without switching to TCP or moving sockets into `public_html`.
- Socket placement is chosen per account type:
  - normal accounts use `~/.redis-managed/`
  - site-isolated accounts use `~/.clwpos/redismanager/`
- The WHM admin now shows whether each managed socket is `isolated` or `legacy`.
- The WHM detail panel wraps long socket paths and Joomla config strings cleanly instead of overlapping them.

### Why

- Joomla sites running inside CloudLinux site isolation cannot reliably see the legacy socket path used by normal accounts.
- A separate visible socket path keeps RedisManager working with the existing Unix-socket model and avoids TCP exposure.

### Validated

- Joomla on `boiraesdeveniments.com` responds `HTTP 200` when pointed at the site-isolated RedisManager socket.
- The Joomla test returned no `RedisException` or `500` errors.

### Not changed

- No TCP fallback was added.
- No socket was moved into `public_html`.
- RedisManager still does not auto-edit Joomla configuration on enable.
- AccelerateWP-managed WordPress Redis remains separate.
