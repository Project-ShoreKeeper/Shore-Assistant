import { describe, it, expect, beforeAll, afterAll } from "vitest";
import { WebSocket } from "ws";
import { startServer, ServerHandle } from "../src/server";

const PORT = 19101;

describe("WebSocket server", () => {
  let handle: ServerHandle;

  beforeAll(async () => {
    handle = await startServer({ host: "127.0.0.1", port: PORT, authToken: "" , maxBufferedBytes: 4 * 1024 * 1024 });
  });

  afterAll(async () => {
    await handle.close();
  });

  async function rpc(ws: WebSocket, method: string, params: any, id: number): Promise<any> {
    return new Promise((resolve, reject) => {
      const onMsg = (raw: Buffer) => {
        const m = JSON.parse(raw.toString());
        if (m.id === id) {
          ws.off("message", onMsg);
          resolve(m);
        }
      };
      ws.on("message", onMsg);
      ws.send(JSON.stringify({ jsonrpc: "2.0", id, method, params }));
      setTimeout(() => reject(new Error("timeout")), 8000);
    });
  }

  it("responds to ping", async () => {
    const ws = new WebSocket(`ws://127.0.0.1:${PORT}`);
    await new Promise<void>((r) => ws.on("open", () => r()));
    const r = await rpc(ws, "ping", {}, 1);
    expect(r.result.pong).toBe(true);
    ws.close();
  }, 10000);

  it("rejects unknown method", async () => {
    const ws = new WebSocket(`ws://127.0.0.1:${PORT}`);
    await new Promise<void>((r) => ws.on("open", () => r()));
    const r = await rpc(ws, "nonexistent", {}, 2);
    expect(r.error.code).toBe(-32601);
    ws.close();
  }, 10000);

  it("requires auth when token configured", async () => {
    const h2 = await startServer({ host: "127.0.0.1", port: PORT + 1, authToken: "secret", maxBufferedBytes: 4 * 1024 * 1024 });
    const ws = new WebSocket(`ws://127.0.0.1:${PORT + 1}`);
    const closeCode = await new Promise<number>((resolve) => {
      ws.on("close", (code) => resolve(code));
      ws.on("error", () => {});
    });
    expect(closeCode).toBeGreaterThanOrEqual(1000);
    await h2.close();
  }, 10000);

  it("accepts auth when token matches", async () => {
    const h2 = await startServer({ host: "127.0.0.1", port: PORT + 2, authToken: "secret", maxBufferedBytes: 4 * 1024 * 1024 });
    const ws = new WebSocket(`ws://127.0.0.1:${PORT + 2}`, { headers: { Authorization: "Bearer secret" } });
    await new Promise<void>((r) => ws.on("open", () => r()));
    const r = await rpc(ws, "ping", {}, 1);
    expect(r.result.pong).toBe(true);
    ws.close();
    await h2.close();
  }, 10000);
});
