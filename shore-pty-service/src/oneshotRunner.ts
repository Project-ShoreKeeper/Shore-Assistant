import { spawn } from "node:child_process";
import type { ShellName } from "./shellResolver.js";

export interface OneshotOptions {
  runId: string;
  command: string;
  shell: ShellName;
  cwd: string;
  timeoutMs: number;
  onOutput: (stream: "stdout" | "stderr", data: string) => void;
}

export interface OneshotResult {
  exitCode: number;
  durationMs: number;
  timedOut: boolean;
}

interface SpawnSpec {
  file: string;
  args: string[];
}

function buildSpawnSpec(shell: ShellName, command: string): SpawnSpec {
  switch (shell) {
    case "powershell":
      return { file: "powershell.exe", args: ["-NoLogo", "-NoProfile", "-Command", command] };
    case "pwsh":
      return { file: "pwsh", args: ["-NoLogo", "-NoProfile", "-Command", command] };
    case "cmd":
      return { file: "cmd.exe", args: ["/c", command] };
    case "bash":
      return { file: "bash", args: ["-c", command] };
    case "wsl":
      // wsl.exe forwards the rest to the default distro; -e picks the executable.
      return { file: "wsl.exe", args: ["-e", "bash", "-c", command] };
    case "anaconda": {
      const root = process.env.ANACONDA_ROOT;
      if (!root) {
        throw new Error(
          "anaconda shell requires ANACONDA_ROOT env var pointing at the Anaconda/Miniconda install dir",
        );
      }
      // /s + outer quotes force cmd to treat the whole wrapped string as one command,
      // so user commands with spaces/quotes are not re-tokenized.
      const wrapped = `"${root}\\Scripts\\activate.bat" "${root}" && ${command}`;
      return { file: "cmd.exe", args: ["/s", "/c", wrapped] };
    }
    default:
      throw new Error(`unsupported shell: ${shell}`);
  }
}

export async function runOneshot(opts: OneshotOptions): Promise<OneshotResult> {
  const spec = buildSpawnSpec(opts.shell, opts.command);
  const start = Date.now();

  const proc = spawn(spec.file, spec.args, {
    cwd: opts.cwd,
    windowsHide: true,
    env: process.env,
  });

  proc.stdout.setEncoding("utf-8");
  proc.stderr.setEncoding("utf-8");
  proc.stdout.on("data", (chunk: string) => opts.onOutput("stdout", chunk));
  proc.stderr.on("data", (chunk: string) => opts.onOutput("stderr", chunk));

  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    proc.kill("SIGKILL");
  }, opts.timeoutMs);

  return await new Promise<OneshotResult>((resolve) => {
    proc.on("exit", (code) => {
      clearTimeout(timer);
      resolve({
        exitCode: timedOut ? -1 : code ?? -1,
        durationMs: Date.now() - start,
        timedOut,
      });
    });
    proc.on("error", () => {
      clearTimeout(timer);
      resolve({ exitCode: -1, durationMs: Date.now() - start, timedOut });
    });
  });
}
