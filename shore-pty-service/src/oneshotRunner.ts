import { spawn } from "node:child_process";

export interface OneshotOptions {
  runId: string;
  command: string;
  shell: "powershell" | "pwsh" | "cmd" | "bash";
  cwd: string;
  timeoutMs: number;
  onOutput: (stream: "stdout" | "stderr", data: string) => void;
}

export interface OneshotResult {
  exitCode: number;
  durationMs: number;
  timedOut: boolean;
}

const SHELL_INVOCATIONS = {
  powershell: { file: "powershell.exe", flags: ["-NoLogo", "-NoProfile", "-Command"] },
  pwsh: { file: "pwsh", flags: ["-NoLogo", "-NoProfile", "-Command"] },
  cmd: { file: "cmd.exe", flags: ["/c"] },
  bash: { file: "bash", flags: ["-c"] },
} as const;

export async function runOneshot(opts: OneshotOptions): Promise<OneshotResult> {
  const inv = SHELL_INVOCATIONS[opts.shell];
  if (!inv) throw new Error(`unsupported shell: ${opts.shell}`);
  const start = Date.now();

  const proc = spawn(inv.file, [...inv.flags, opts.command], {
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
