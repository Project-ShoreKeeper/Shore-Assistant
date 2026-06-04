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
6. `docker compose ps` — all three services should be `healthy` in ~30 s.

## Updates
`git pull && docker compose pull && docker compose up -d`.

## Backup (manual)
- Redis: `docker exec shore-redis redis-cli BGSAVE`, then rsync
  `/var/lib/shore/redis/dump.rdb`.
- Postgres + Qdrant: stop the container, rsync the data dir, restart.

## Reset (destroys ALL memory)
`docker compose down -v && sudo rm -rf /var/lib/shore/{redis,postgres,qdrant}/*`
