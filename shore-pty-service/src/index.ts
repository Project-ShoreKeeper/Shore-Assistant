import "dotenv/config";
import { startServer } from "./server.js";
import { logger } from "./logger.js";

const host = process.env.PTY_WS_HOST ?? "127.0.0.1";
const port = parseInt(process.env.PTY_WS_PORT ?? "9100", 10);
const authToken = process.env.PTY_AUTH_TOKEN ?? "";
const maxBufferedBytes = parseInt(process.env.PTY_MAX_BUFFERED_BYTES ?? "4194304", 10);

async function main() {
  const handle = await startServer({ host, port, authToken, maxBufferedBytes });

  const shutdown = async (sig: string) => {
    logger.info({ sig }, "shutting down");
    await handle.close();
    process.exit(0);
  };
  process.on("SIGINT", () => shutdown("SIGINT"));
  process.on("SIGTERM", () => shutdown("SIGTERM"));
}

main().catch((e) => {
  logger.error({ err: e?.message }, "fatal startup error");
  process.exit(2);
});
