import { SessionManager } from "./sessionManager.js";
import { runOneshot } from "./oneshotRunner.js";
import { ErrorCode } from "./rpc.js";

const VERSION = "0.1.0";

export interface HandlersContext {
  sessionManager: SessionManager;
  notify: (method: string, params: Record<string, unknown>) => void;
}

export type Handler = (params: any) => Promise<any>;

export class MethodError extends Error {
  constructor(public code: ErrorCode, message: string) {
    super(message);
  }
}

export function buildHandlers(ctx: HandlersContext): Record<string, Handler> {
  return {
    "ping": async () => ({ pong: true, version: VERSION }),

    "oneshot.run": async (p) => {
      const result = await runOneshot({
        runId: p.run_id,
        command: p.command,
        shell: p.shell,
        cwd: p.cwd,
        timeoutMs: p.timeout_ms,
        onOutput: (stream, data) =>
          ctx.notify("oneshot.output", { run_id: p.run_id, stream, data }),
      });
      ctx.notify("oneshot.exit", { run_id: p.run_id, exit_code: result.exitCode });
      return {
        exit_code: result.exitCode,
        duration_ms: result.durationMs,
        timed_out: result.timedOut,
      };
    },

    "session.open": async (p) => {
      try {
        const r = ctx.sessionManager.open({
          sessionId: p.session_id,
          name: p.name,
          shell: p.shell,
          cwd: p.cwd,
          cols: p.cols ?? 80,
          rows: p.rows ?? 24,
        });
        return { session_id: r.sessionId, pid: r.pid };
      } catch (e: any) {
        if (/already exists/i.test(e.message)) throw new MethodError(ErrorCode.SessionAlreadyExists, e.message);
        if (/unsupported shell/i.test(e.message)) throw new MethodError(ErrorCode.ShellNotFound, e.message);
        throw new MethodError(ErrorCode.SpawnFailed, e.message);
      }
    },

    "session.send": async (p) => {
      try {
        ctx.sessionManager.send(p.session_id, p.data);
        return { ok: true };
      } catch (e: any) {
        if (/not found/i.test(e.message)) throw new MethodError(ErrorCode.SessionNotFound, e.message);
        if (/dead/i.test(e.message)) throw new MethodError(ErrorCode.WriteToDeadSession, e.message);
        throw new MethodError(ErrorCode.InternalError, e.message);
      }
    },

    "session.resize": async (p) => {
      try {
        ctx.sessionManager.resize(p.session_id, p.cols, p.rows);
        return { ok: true };
      } catch (e: any) {
        if (/not found/i.test(e.message)) throw new MethodError(ErrorCode.SessionNotFound, e.message);
        throw new MethodError(ErrorCode.InternalError, e.message);
      }
    },

    "session.close": async (p) => {
      await ctx.sessionManager.close(p.session_id);
      return { closed: true };
    },

    "session.list": async () => ctx.sessionManager.list(),
  };
}
