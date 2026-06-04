# Shore Memory Stack — Server Setup

## Prerequisites
- Linux server with Docker + compose plugin (v2+).
- Static LAN IP (e.g. 192.168.1.50).

## First-time setup
1. SSH to the server.
2. `git clone <repo>` and `cd Shore-Assistant/deploy/memory`.
3. `cp .env.example .env` and fill in `LAN_BIND_IP`, `POSTGRES_PASSWORD`.
4. Create data dirs with the right UIDs:
   ```
   sudo mkdir -p /var/lib/shore/{redis,postgres,qdrant}
   sudo chown 999:999    /var/lib/shore/redis
   sudo chown 70:70      /var/lib/shore/postgres
   sudo chown 1000:1000  /var/lib/shore/qdrant
   ```
5. `docker compose up -d`
6. `docker compose ps` — Redis and Postgres should be `healthy` in
   ~30 s. Qdrant reports as `Up` only (no health state — its distroless
   image has no probe tool); verify it with
   `curl -fsS http://<LAN_BIND_IP>:6333/healthz` from the host.

### Port collisions on a shared server

If another stack on the same box already binds 6379 (Redis), 5432
(Postgres), or 6333/6334 (Qdrant), uncomment the `*_HOST_PORT`
overrides in `.env`:

```bash
REDIS_HOST_PORT=16379
POSTGRES_HOST_PORT=15432
QDRANT_REST_PORT=16333
QDRANT_GRPC_PORT=16334
```

Update the back-end's `.env` accordingly so `REDIS_URL`, `POSTGRES_URL`,
and `QDRANT_URL` use the same non-default ports.

## Updates
`git pull && docker compose pull && docker compose up -d`.

## Backup (manual)
- Redis: `docker exec shore-redis redis-cli BGSAVE`, then rsync
  `/var/lib/shore/redis/dump.rdb`.
- Postgres + Qdrant: stop the container, rsync the data dir, restart.

## Reset (destroys ALL memory)
`docker compose down -v && sudo rm -rf /var/lib/shore/{redis,postgres,qdrant}/*`
