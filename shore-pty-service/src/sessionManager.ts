import { PtySession } from "./ptySession.js";

export interface SessionManagerOptions {
  onData: (sessionId: string, data: string) => void;
  onExit: (sessionId: string, exitCode: number, signal?: number) => void;
  onOutputDropped: (sessionId: string, droppedBytes: number) => void;
  maxBufferedBytes: number;
  isBackpressured: () => boolean;
}

export interface OpenOptions {
  sessionId: string;
  name: string;
  shell: string;
  cwd: string;
  cols: number;
  rows: number;
}

interface Entry {
  session: PtySession;
  name: string;
  shell: string;
  cwd: string;
  startedAt: number;
  lastActivity: number;
}

export class SessionManager {
  private readonly entries = new Map<string, Entry>();
  private readonly opts: SessionManagerOptions;
  private readonly exitWaiters = new Map<string, Array<() => void>>();

  constructor(opts: SessionManagerOptions) {
    this.opts = opts;
  }

  open(o: OpenOptions): { sessionId: string; pid: number } {
    if (this.entries.has(o.sessionId)) {
      throw new Error(`session already exists: ${o.sessionId}`);
    }
    const session = new PtySession({
      sessionId: o.sessionId,
      shell: o.shell,
      cwd: o.cwd,
      cols: o.cols,
      rows: o.rows,
      onData: (d) => this.handleData(o.sessionId, d),
      onExit: (code, sig) => this.handleExit(o.sessionId, code, sig),
    });
    this.entries.set(o.sessionId, {
      session,
      name: o.name,
      shell: o.shell,
      cwd: o.cwd,
      startedAt: Date.now(),
      lastActivity: Date.now(),
    });
    return { sessionId: o.sessionId, pid: session.pid };
  }

  send(sessionId: string, data: string): void {
    const e = this.entries.get(sessionId);
    if (!e) throw new Error(`session not found: ${sessionId}`);
    e.lastActivity = Date.now();
    e.session.write(data);
  }

  resize(sessionId: string, cols: number, rows: number): void {
    const e = this.entries.get(sessionId);
    if (!e) throw new Error(`session not found: ${sessionId}`);
    e.session.resize(cols, rows);
  }

  close(sessionId: string): Promise<void> {
    const e = this.entries.get(sessionId);
    if (!e) return Promise.resolve();
    return new Promise<void>((resolve) => {
      const waiters = this.exitWaiters.get(sessionId) ?? [];
      waiters.push(resolve);
      this.exitWaiters.set(sessionId, waiters);
      e.session.kill();
      // entry will be removed in handleExit
    });
  }

  list() {
    return Array.from(this.entries.entries()).map(([sid, e]) => ({
      session_id: sid,
      name: e.name,
      shell: e.shell,
      cwd: e.cwd,
      pid: e.session.pid,
      idle_seconds: Math.floor((Date.now() - e.lastActivity) / 1000),
    }));
  }

  async closeAll(): Promise<void> {
    for (const sid of Array.from(this.entries.keys())) {
      await this.close(sid);
    }
  }

  private handleData(sessionId: string, data: string): void {
    const e = this.entries.get(sessionId);
    if (!e) return;
    e.lastActivity = Date.now();
    if (this.opts.isBackpressured()) {
      this.opts.onOutputDropped(sessionId, Buffer.byteLength(data, "utf-8"));
      return;
    }
    this.opts.onData(sessionId, data);
  }

  private handleExit(sessionId: string, code: number, signal?: number): void {
    this.entries.delete(sessionId);
    this.opts.onExit(sessionId, code, signal);
    const waiters = this.exitWaiters.get(sessionId);
    if (waiters) {
      this.exitWaiters.delete(sessionId);
      for (const resolve of waiters) resolve();
    }
  }
}
