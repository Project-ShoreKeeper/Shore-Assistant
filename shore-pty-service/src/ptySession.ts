import * as pty from "node-pty";
import { resolveShell } from "./shellResolver.js";

export interface PtySessionOptions {
  sessionId: string;
  shell: string;
  cwd: string;
  cols: number;
  rows: number;
  onData: (data: string) => void;
  onExit: (exitCode: number, signal?: number) => void;
}

export class PtySession {
  readonly sessionId: string;
  readonly pid: number;
  private readonly proc: pty.IPty;
  private exited = false;

  constructor(opts: PtySessionOptions) {
    this.sessionId = opts.sessionId;
    const resolved = resolveShell(opts.shell);
    this.proc = pty.spawn(resolved.file, resolved.args, {
      cwd: opts.cwd,
      cols: opts.cols,
      rows: opts.rows,
      env: process.env as { [k: string]: string },
    });
    this.pid = this.proc.pid;
    this.proc.onData((d) => opts.onData(d));
    this.proc.onExit(({ exitCode, signal }) => {
      this.exited = true;
      opts.onExit(exitCode, signal);
    });
  }

  write(data: string): void {
    if (this.exited) throw new Error("write to dead session");
    this.proc.write(data);
  }

  resize(cols: number, rows: number): void {
    if (this.exited) return;
    try {
      this.proc.resize(cols, rows);
    } catch {
      /* swallow — terminal already gone */
    }
  }

  kill(): void {
    if (this.exited) return;
    try {
      this.proc.kill();
    } catch {
      /* already dead */
    }
  }
}
