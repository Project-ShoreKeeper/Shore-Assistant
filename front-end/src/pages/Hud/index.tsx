/**
 * /hud — ambient overlay page rendered inside the transparent `hud` Tauri
 * window. Purely presentational: all data arrives over Tauri events (see
 * hud-bridge.service.ts); no WebSocket, no REST, no auth.
 */
import { useEffect } from "react";
import { isTauri } from "@Shore/utils/tauri.util";
import { emitHudFocusMain } from "@Shore/services/hud-bridge.service";
import { useHudState } from "./useHudState";
import EdgeRing from "./EdgeRing";
import AgentStatusWidget from "./widgets/AgentStatusWidget";
import LastTaskWidget from "./widgets/LastTaskWidget";
import AnswerWidget from "./widgets/AnswerWidget";
import ConnectionWidget from "./widgets/ConnectionWidget";
import "./hud.css";

export default function PageHud() {
  const { state, active, linked } = useHudState();

  useEffect(() => {
    document.documentElement.classList.add("hud-transparent");
    return () => document.documentElement.classList.remove("hud-transparent");
  }, []);

  // Esc (receivable only while active/focusable) drops back to passive.
  useEffect(() => {
    if (!isTauri()) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      void import("@tauri-apps/api/core").then(({ invoke }) =>
        invoke("hud_set_mode", { active: false }),
      );
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const focusMain = () => {
    if (active) emitHudFocusMain();
  };

  return (
    <div className={`hud-root${active ? " hud-active" : ""}`}>
      <EdgeRing />
      <AgentStatusWidget status={state?.agent ?? "idle"} onClick={focusMain} />
      <LastTaskWidget task={state?.lastTask ?? null} onClick={focusMain} />
      <AnswerWidget answer={state?.answer ?? null} onClick={focusMain} />
      <ConnectionWidget
        connection={state?.connection ?? "offline"}
        linked={linked}
        onClick={focusMain}
      />
    </div>
  );
}
