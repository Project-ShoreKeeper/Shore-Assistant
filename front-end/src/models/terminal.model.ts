export interface TerminalSession {
  session_id: string;
  name: string;
  shell: string;
  cwd: string;
  idle_seconds?: number;
  last_output_preview?: string;
}

export interface OneShotRun {
  run_id: string;
  command: string;
  shell: string;
  cwd: string;
  startedAt: number;
  endedAt?: number;
  exitCode?: number;
  stdout: string;
  stderr: string;
  truncated?: boolean;
}

export interface PendingConfirm {
  request_id: string;
  command: string;
  shell: string;
  cwd: string;
  reason: string;
}

export type TerminalServerMessage =
  | { type: "terminal_confirm_request"; request_id: string; command: string; shell: string; cwd: string; reason: string }
  | { type: "terminal_oneshot_start"; run_id: string; command: string; shell: string; cwd: string }
  | { type: "terminal_oneshot_output"; run_id: string; stream: "stdout" | "stderr"; data: string }
  | { type: "terminal_oneshot_end"; run_id: string; exit_code: number; duration_ms: number; truncated: boolean }
  | { type: "terminal_session_opened"; session_id: string; name: string; shell: string; cwd: string; pid: number }
  | { type: "terminal_session_output"; session_id: string; data: string }
  | { type: "terminal_session_closed"; session_id: string; name?: string; reason: string; exit_code?: number | null }
  | { type: "terminal_sessions_snapshot"; sessions: TerminalSession[] };
