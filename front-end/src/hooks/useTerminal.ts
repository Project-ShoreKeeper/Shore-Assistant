import { useCallback, useEffect, useState } from "react";
import {
  OneShotRun,
  PendingConfirm,
  TerminalServerMessage,
  TerminalSession,
} from "../models/terminal.model";
import chatWebsocketService from "../services/chat-websocket.service";

export function useTerminal() {
  const [sessions, setSessions] = useState<TerminalSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [sessionOutput, setSessionOutput] = useState<Record<string, string>>({});
  const [oneShotRuns, setOneShotRuns] = useState<OneShotRun[]>([]);
  const [pendingConfirms, setPendingConfirms] = useState<PendingConfirm[]>([]);

  useEffect(() => {
    const unsubscribe = chatWebsocketService.onTerminalMessage((raw: TerminalServerMessage) => {
      switch (raw.type) {
        case "terminal_confirm_request":
          setPendingConfirms((prev) => [
            ...prev,
            {
              request_id: raw.request_id,
              command: raw.command,
              shell: raw.shell,
              cwd: raw.cwd,
              reason: raw.reason,
            },
          ]);
          break;
        case "terminal_oneshot_start":
          setOneShotRuns((prev) => [
            ...prev,
            {
              run_id: raw.run_id,
              command: raw.command,
              shell: raw.shell,
              cwd: raw.cwd,
              startedAt: Date.now(),
              stdout: "",
              stderr: "",
            },
          ]);
          break;
        case "terminal_oneshot_output":
          setOneShotRuns((prev) =>
            prev.map((r) =>
              r.run_id === raw.run_id
                ? { ...r, [raw.stream]: r[raw.stream] + raw.data }
                : r,
            ),
          );
          break;
        case "terminal_oneshot_end":
          setOneShotRuns((prev) =>
            prev.map((r) =>
              r.run_id === raw.run_id
                ? {
                    ...r,
                    endedAt: Date.now(),
                    exitCode: raw.exit_code,
                    truncated: raw.truncated,
                  }
                : r,
            ),
          );
          break;
        case "terminal_session_opened":
          setSessions((prev) => [
            ...prev.filter((s) => s.session_id !== raw.session_id),
            {
              session_id: raw.session_id,
              name: raw.name,
              shell: raw.shell,
              cwd: raw.cwd,
            },
          ]);
          setActiveSessionId(raw.session_id);
          break;
        case "terminal_session_output":
          setSessionOutput((prev) => ({
            ...prev,
            [raw.session_id]: (prev[raw.session_id] || "") + raw.data,
          }));
          break;
        case "terminal_session_closed":
          setSessions((prev) => prev.filter((s) => s.session_id !== raw.session_id));
          setSessionOutput((prev) => {
            const next = { ...prev };
            delete next[raw.session_id];
            return next;
          });
          setActiveSessionId((cur) => (cur === raw.session_id ? null : cur));
          break;
        case "terminal_sessions_snapshot":
          setSessions(raw.sessions);
          break;
      }
    });

    chatWebsocketService.sendTerminalMessage({ type: "terminal_resync" });

    return unsubscribe;
  }, []);

  const respondConfirm = useCallback(
    (request_id: string, decision: "approve" | "deny" | "always_allow") => {
      chatWebsocketService.sendTerminalMessage({
        type: "terminal_confirm_response",
        request_id,
        decision,
      });
      setPendingConfirms((prev) => prev.filter((p) => p.request_id !== request_id));
    },
    [],
  );

  const sendInput = useCallback((session_id: string, data: string) => {
    chatWebsocketService.sendTerminalMessage({
      type: "terminal_user_input",
      session_id,
      data,
    });
  }, []);

  const closeSession = useCallback((session_id: string) => {
    chatWebsocketService.sendTerminalMessage({
      type: "terminal_close_session",
      session_id,
    });
  }, []);

  const resizeSession = useCallback(
    (session_id: string, cols: number, rows: number) => {
      chatWebsocketService.sendTerminalMessage({
        type: "terminal_resize",
        session_id,
        cols,
        rows,
      });
    },
    [],
  );

  return {
    sessions,
    activeSessionId,
    setActiveSessionId,
    sessionOutput,
    oneShotRuns,
    pendingConfirms,
    respondConfirm,
    sendInput,
    closeSession,
    resizeSession,
  };
}
