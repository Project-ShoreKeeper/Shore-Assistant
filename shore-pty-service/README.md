# shore-pty-service

Terminal execution microservice for Shore Assistant. Wraps `node-pty` for PTY sessions and `child_process` for one-shot commands, exposing a JSON-RPC 2.0 WebSocket API on `ws://127.0.0.1:9100`.

The FastAPI back-end is the only client. Browser does not connect here.

## Run

```bash
npm install
npm run build
npm start
```

Or in dev (auto-reload):

```bash
npm run dev
```

## Configuration

Copy `.env.example` to `.env` and adjust.

| Var | Default | Purpose |
|---|---|---|
| `PTY_WS_HOST` | `127.0.0.1` | bind host (localhost only) |
| `PTY_WS_PORT` | `9100` | WS port |
| `PTY_AUTH_TOKEN` | `` | optional shared secret; clients must send `Authorization: Bearer <token>` |
| `PTY_MAX_BUFFERED_BYTES` | `4194304` | per-session backpressure threshold (4 MB) |
| `PTY_LOG_LEVEL` | `info` | pino log level |

## Protocol

See `docs/superpowers/specs/2026-06-03-node-pty-microservice-design.md` section 3 for the full JSON-RPC method/event catalog.

## Requirements

- Node 20+
- On Windows: Visual Studio Build Tools 2022 with "Desktop development with C++" workload (for compiling `node-pty` native bindings).

## Tests

```bash
npm test
```

Tests spawn real PowerShell processes — Windows host required.
