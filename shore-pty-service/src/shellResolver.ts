export const SUPPORTED_SHELLS = ["powershell", "pwsh", "cmd", "bash"] as const;
export type ShellName = (typeof SUPPORTED_SHELLS)[number];

export interface ResolvedShell {
  file: string;
  args: string[];
}

const MAP: Record<ShellName, ResolvedShell> = {
  powershell: { file: "powershell.exe", args: [] },
  pwsh: { file: "pwsh", args: [] },
  cmd: { file: "cmd.exe", args: [] },
  bash: { file: "bash", args: [] },
};

export function resolveShell(shell: string): ResolvedShell {
  if (!(SUPPORTED_SHELLS as readonly string[]).includes(shell)) {
    throw new Error(`unsupported shell: ${shell}`);
  }
  return MAP[shell as ShellName];
}
