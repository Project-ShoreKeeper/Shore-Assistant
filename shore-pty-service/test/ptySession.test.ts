import { describe, it, expect, vi } from "vitest";
import { PtySession } from "../src/ptySession";

describe("PtySession", () => {
  it("spawns a powershell session and reports pid", async () => {
    const onData = vi.fn();
    const onExit = vi.fn();
    const s = new PtySession({
      sessionId: "abc",
      shell: "powershell",
      cwd: process.cwd(),
      cols: 80,
      rows: 24,
      onData,
      onExit,
    });
    expect(s.pid).toBeGreaterThan(0);
    await new Promise((r) => setTimeout(r, 500));
    expect(onData).toHaveBeenCalled();
    s.kill();
    await new Promise((r) => setTimeout(r, 300));
    expect(onExit).toHaveBeenCalled();
  }, 10000);

  it("write() echoes through PTY", async () => {
    const chunks: string[] = [];
    const s = new PtySession({
      sessionId: "x",
      shell: "powershell",
      cwd: process.cwd(),
      cols: 80,
      rows: 24,
      onData: (d) => chunks.push(d),
      onExit: () => {},
    });
    await new Promise((r) => setTimeout(r, 600));
    s.write("echo hello-pty\r\n");
    await new Promise((r) => setTimeout(r, 1500));
    expect(chunks.join("")).toContain("hello-pty");
    s.kill();
  }, 10000);

  it("resize does not throw", () => {
    const s = new PtySession({
      sessionId: "r",
      shell: "powershell",
      cwd: process.cwd(),
      cols: 80,
      rows: 24,
      onData: () => {},
      onExit: () => {},
    });
    expect(() => s.resize(120, 40)).not.toThrow();
    s.kill();
  });
});
