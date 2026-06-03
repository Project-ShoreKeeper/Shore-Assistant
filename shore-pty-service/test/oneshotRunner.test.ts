import { describe, it, expect, vi } from "vitest";
import { runOneshot } from "../src/oneshotRunner";

describe("runOneshot", () => {
  it("returns exit code 0 for successful command", async () => {
    const onOutput = vi.fn();
    const result = await runOneshot({
      runId: "r1",
      command: "echo hello",
      shell: "powershell",
      cwd: process.cwd(),
      timeoutMs: 10000,
      onOutput,
    });
    expect(result.exitCode).toBe(0);
    expect(onOutput).toHaveBeenCalled();
  }, 15000);

  it("returns non-zero exit code for failed command", async () => {
    const result = await runOneshot({
      runId: "r2",
      command: "exit 7",
      shell: "powershell",
      cwd: process.cwd(),
      timeoutMs: 10000,
      onOutput: () => {},
    });
    expect(result.exitCode).toBe(7);
  }, 15000);

  it("returns exit code -1 on timeout", async () => {
    const result = await runOneshot({
      runId: "r3",
      command: "Start-Sleep -Seconds 5",
      shell: "powershell",
      cwd: process.cwd(),
      timeoutMs: 500,
      onOutput: () => {},
    });
    expect(result.exitCode).toBe(-1);
    expect(result.timedOut).toBe(true);
  }, 10000);

  it("separates stdout and stderr in onOutput callbacks", async () => {
    const events: { stream: string; data: string }[] = [];
    await runOneshot({
      runId: "r4",
      command: "Write-Output out; [Console]::Error.WriteLine('err')",
      shell: "powershell",
      cwd: process.cwd(),
      timeoutMs: 10000,
      onOutput: (stream, data) => events.push({ stream, data }),
    });
    const streams = events.map((e) => e.stream);
    expect(streams).toContain("stdout");
    expect(streams).toContain("stderr");
  }, 15000);
});
