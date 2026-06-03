import { describe, it, expect } from "vitest";
import { resolveShell, SUPPORTED_SHELLS } from "../src/shellResolver";

describe("shellResolver", () => {
  it("resolves powershell", () => {
    expect(resolveShell("powershell")).toEqual({ file: "powershell.exe", args: [] });
  });
  it("resolves cmd", () => {
    expect(resolveShell("cmd")).toEqual({ file: "cmd.exe", args: [] });
  });
  it("resolves bash", () => {
    expect(resolveShell("bash")).toEqual({ file: "bash", args: [] });
  });
  it("resolves pwsh", () => {
    expect(resolveShell("pwsh")).toEqual({ file: "pwsh", args: [] });
  });
  it("throws on unknown shell", () => {
    expect(() => resolveShell("zsh" as any)).toThrow(/unsupported shell/i);
  });
  it("exposes supported list", () => {
    expect(SUPPORTED_SHELLS).toEqual(["powershell", "pwsh", "cmd", "bash"]);
  });
});
