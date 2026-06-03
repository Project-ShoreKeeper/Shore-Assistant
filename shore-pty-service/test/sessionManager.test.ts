import { describe, it, expect, vi } from "vitest";
import { SessionManager } from "../src/sessionManager";

describe("SessionManager", () => {
  it("opens, lists, and closes a session", async () => {
    const events: any[] = [];
    const mgr = new SessionManager({
      onData: (sid, d) => events.push({ k: "data", sid, d }),
      onExit: (sid, code) => events.push({ k: "exit", sid, code }),
      onOutputDropped: () => {},
      maxBufferedBytes: 4 * 1024 * 1024,
      isBackpressured: () => false,
    });

    const { sessionId, pid } = mgr.open({
      sessionId: "s1",
      name: "dev",
      shell: "powershell",
      cwd: process.cwd(),
      cols: 80,
      rows: 24,
    });
    expect(sessionId).toBe("s1");
    expect(pid).toBeGreaterThan(0);

    expect(mgr.list()).toHaveLength(1);
    expect(mgr.list()[0].name).toBe("dev");

    await mgr.close("s1");
    expect(mgr.list()).toHaveLength(0);
  }, 10000);

  it("rejects duplicate session_id", () => {
    const mgr = new SessionManager({
      onData: () => {},
      onExit: () => {},
      onOutputDropped: () => {},
      maxBufferedBytes: 4 * 1024 * 1024,
      isBackpressured: () => false,
    });
    mgr.open({ sessionId: "dup", name: "a", shell: "powershell", cwd: process.cwd(), cols: 80, rows: 24 });
    expect(() => mgr.open({ sessionId: "dup", name: "b", shell: "powershell", cwd: process.cwd(), cols: 80, rows: 24 })).toThrow(/already exists/i);
    mgr.close("dup");
  });

  it("send() to unknown session throws", () => {
    const mgr = new SessionManager({
      onData: () => {},
      onExit: () => {},
      onOutputDropped: () => {},
      maxBufferedBytes: 4 * 1024 * 1024,
      isBackpressured: () => false,
    });
    expect(() => mgr.send("ghost", "hi\r\n")).toThrow(/not found/i);
  });

  it("emits onOutputDropped when backpressured", () => {
    const drops: any[] = [];
    let drop = true;
    const mgr = new SessionManager({
      onData: () => {},
      onExit: () => {},
      onOutputDropped: (sid, bytes) => drops.push({ sid, bytes }),
      maxBufferedBytes: 4 * 1024 * 1024,
      isBackpressured: () => drop,
    });
    mgr.open({ sessionId: "bp", name: "bp", shell: "powershell", cwd: process.cwd(), cols: 80, rows: 24 });
    // simulate output arrival via the internal handler
    (mgr as any).handleData("bp", "x".repeat(1000));
    expect(drops.length).toBeGreaterThan(0);
    mgr.close("bp");
  });
});
