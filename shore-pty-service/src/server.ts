import { WebSocketServer, WebSocket } from "ws";
import type { IncomingMessage } from "node:http";
import { parseMessage, encodeResponse, encodeError, encodeNotification, ErrorCode } from "./rpc";
import { SessionManager } from "./sessionManager";
import { buildHandlers, MethodError } from "./methods";
import { logger } from "./logger";

export interface ServerConfig {
  host: string;
  port: number;
  authToken: string;
  maxBufferedBytes: number;
}

export interface ServerHandle {
  close(): Promise<void>;
}

export async function startServer(cfg: ServerConfig): Promise<ServerHandle> {
  const wss = new WebSocketServer({ host: cfg.host, port: cfg.port });

  wss.on("connection", (ws: WebSocket, req: IncomingMessage) => {
    if (cfg.authToken) {
      const got = req.headers["authorization"];
      if (got !== `Bearer ${cfg.authToken}`) {
        logger.warn("rejecting unauthenticated connection");
        ws.close(1008, "unauthorized");
        return;
      }
    }

    const send = (s: string) => {
      if (ws.readyState === ws.OPEN) ws.send(s);
    };
    const isBackpressured = () => ws.bufferedAmount > cfg.maxBufferedBytes;
    const sessionManager = new SessionManager({
      onData: (sid, data) => send(encodeNotification("session.output", { session_id: sid, data })),
      onExit: (sid, code, signal) =>
        send(encodeNotification("session.exit", { session_id: sid, exit_code: code, signal: signal ?? null, reason: "natural" })),
      onOutputDropped: (sid, bytes) =>
        send(encodeNotification("session.output_dropped", { session_id: sid, dropped_bytes: bytes })),
      maxBufferedBytes: cfg.maxBufferedBytes,
      isBackpressured,
    });

    const handlers = buildHandlers({
      sessionManager,
      notify: (method, params) => send(encodeNotification(method, params)),
    });

    ws.on("message", async (raw) => {
      const parsed = parseMessage(raw.toString());
      if (parsed.kind === "invalid") {
        send(encodeError(null, ErrorCode.InvalidRequest, parsed.reason));
        return;
      }
      const handler = handlers[parsed.method];
      if (!handler) {
        send(encodeError(parsed.id, ErrorCode.MethodNotFound, `unknown method: ${parsed.method}`));
        return;
      }
      try {
        const result = await handler(parsed.params);
        send(encodeResponse(parsed.id, result));
      } catch (e: any) {
        if (e instanceof MethodError) {
          send(encodeError(parsed.id, e.code, e.message));
        } else {
          logger.error({ err: e?.message }, "internal handler error");
          send(encodeError(parsed.id, ErrorCode.InternalError, e?.message ?? "unknown"));
        }
      }
    });

    ws.on("close", async () => {
      await sessionManager.closeAll();
    });
  });

  await new Promise<void>((resolve) => wss.on("listening", () => resolve()));
  logger.info({ host: cfg.host, port: cfg.port }, "shore-pty-service listening");

  return {
    close: () =>
      new Promise<void>((resolve) => {
        wss.close(() => resolve());
        for (const c of wss.clients) c.close();
      }),
  };
}
