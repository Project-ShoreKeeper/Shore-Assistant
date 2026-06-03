import { describe, it, expect, vi } from "vitest";
import { buildHandlers } from "../src/methods";
import { SessionManager } from "../src/sessionManager";

function mkMgr() {
  return new SessionManager({
    onData: () => {},
    onExit: () => {},
    onOutputDropped: () => {},
    maxBufferedBytes: 4 * 1024 * 1024,
    isBackpressured: () => false,
  });
}

describe("method handlers", () => {
  it("ping returns version", async () => {
    const h = buildHandlers({ sessionManager: mkMgr(), notify: () => {} });
    const r = await h["ping"]({});
    expect(r).toMatchObject({ pong: true });
    expect(typeof r.version).toBe("string");
  });

  it("session.open returns session_id + pid", async () => {
    const mgr = mkMgr();
    const h = buildHandlers({ sessionManager: mgr, notify: () => {} });
    const r = await h["session.open"]({
      name: "t",
      session_id: "abc",
      shell: "powershell",
      cwd: process.cwd(),
      cols: 80,
      rows: 24,
    });
    expect(r.session_id).toBe("abc");
    expect(r.pid).toBeGreaterThan(0);
    await mgr.close("abc");
  }, 10000);

  it("oneshot.run emits oneshot.output and returns exit_code", async () => {
    const events: any[] = [];
    const h = buildHandlers({ sessionManager: mkMgr(), notify: (m, p) => events.push({ m, p }) });
    const r = await h["oneshot.run"]({
      run_id: "rid",
      command: "echo hi",
      shell: "powershell",
      cwd: process.cwd(),
      timeout_ms: 10000,
    });
    expect(r.exit_code).toBe(0);
    const outputs = events.filter((e) => e.m === "oneshot.output");
    expect(outputs.length).toBeGreaterThan(0);
  }, 15000);
});
