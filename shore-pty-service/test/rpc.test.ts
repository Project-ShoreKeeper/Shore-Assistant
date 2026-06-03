import { describe, it, expect } from "vitest";
import { parseMessage, encodeResponse, encodeError, encodeNotification, ErrorCode } from "../src/rpc";

describe("rpc parser", () => {
  it("parses a valid request", () => {
    const msg = parseMessage('{"jsonrpc":"2.0","id":1,"method":"ping","params":{}}');
    expect(msg).toEqual({ kind: "request", id: 1, method: "ping", params: {} });
  });

  it("rejects non-JSON", () => {
    const msg = parseMessage("not json");
    expect(msg.kind).toBe("invalid");
  });

  it("rejects wrong jsonrpc version", () => {
    const msg = parseMessage('{"jsonrpc":"1.0","id":1,"method":"x"}');
    expect(msg.kind).toBe("invalid");
  });

  it("parses request with missing params as empty object", () => {
    const msg = parseMessage('{"jsonrpc":"2.0","id":2,"method":"ping"}');
    expect(msg).toEqual({ kind: "request", id: 2, method: "ping", params: {} });
  });
});

describe("rpc encoders", () => {
  it("encodes a response", () => {
    const s = encodeResponse(7, { pong: true });
    expect(JSON.parse(s)).toEqual({ jsonrpc: "2.0", id: 7, result: { pong: true } });
  });

  it("encodes an error", () => {
    const s = encodeError(7, ErrorCode.MethodNotFound, "boom");
    expect(JSON.parse(s)).toEqual({
      jsonrpc: "2.0",
      id: 7,
      error: { code: -32601, message: "boom" },
    });
  });

  it("encodes a notification (no id)", () => {
    const s = encodeNotification("session.output", { session_id: "x", data: "hi" });
    expect(JSON.parse(s)).toEqual({
      jsonrpc: "2.0",
      method: "session.output",
      params: { session_id: "x", data: "hi" },
    });
  });
});
