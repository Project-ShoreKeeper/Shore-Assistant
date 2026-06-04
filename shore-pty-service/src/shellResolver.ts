export const SUPPORTED_SHELLS = ["powershell", "pwsh", "cmd", "bash", "wsl", "anaconda"] as const;
export type ShellName = (typeof SUPPORTED_SHELLS)[number];

export interface ResolvedShell {
  file: string;
  args: string[];
}

function resolveAnaconda(): ResolvedShell {
  const root = process.env.ANACONDA_ROOT;
  if (!root) {
    throw new Error(
      "anaconda shell requires ANACONDA_ROOT env var pointing at the Anaconda/Miniconda install dir",
    );
  }
  // cmd.exe /K activate.bat <root> — keeps the activated env open for interactive use.
  // CreateProcess will quote args containing spaces, so paths like "C:\Program Files\Anaconda3" work.
  return { file: "cmd.exe", args: ["/K", `${root}\\Scripts\\activate.bat`, root] };
}

export function resolveShell(shell: string): ResolvedShell {
  switch (shell) {
    case "powershell":
      return { file: "powershell.exe", args: [] };
    case "pwsh":
      return { file: "pwsh", args: [] };
    case "cmd":
      return { file: "cmd.exe", args: [] };
    case "bash":
      return { file: "bash", args: [] };
    case "wsl":
      return { file: "wsl.exe", args: [] };
    case "anaconda":
      return resolveAnaconda();
    default:
      throw new Error(`unsupported shell: ${shell}`);
  }
}
