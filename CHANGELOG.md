# Changelog

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
