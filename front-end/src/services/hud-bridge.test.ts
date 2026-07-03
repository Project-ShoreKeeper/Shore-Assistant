import { describe, expect, it } from "vitest";

import { deriveHudState } from "./hud-bridge.service";

describe("deriveHudState", () => {
  it("publishes bounded answer and sanitized task metadata", () => {
    const answer = "x".repeat(4_500);
    const state = deriveHudState({
      wsStatus: "OPEN",
      lastCloseCode: null,
      cuaRunning: false,
      isAssistantThinking: false,
      messages: [{
        id: "message-1",
        role: "assistant",
        text: answer,
        agentActions: [{
          id: "action-1",
          tool: "run_command",
          detail: "SECRET_TOKEN=do-not-publish",
          status: "completed",
          timestamp: new Date(1234),
        }],
      }],
    });

    expect(state.answer).toEqual({
      messageId: "message-1",
      text: "x".repeat(4_000),
    });
    expect(state.lastTask).toEqual({
      messageId: "message-1",
      actionId: "action-1",
      tool: "run_command",
      status: "completed",
      summary: "run_command completed",
      ts: 1234,
    });
    expect(JSON.stringify(state)).not.toContain("SECRET_TOKEN");
  });

  it("disables reconnect after an authentication close", () => {
    const state = deriveHudState({
      wsStatus: "CLOSED",
      lastCloseCode: 4401,
      cuaRunning: false,
      isAssistantThinking: false,
      messages: [],
    });

    expect(state.capabilities.retryConnection).toBe(false);
  });

  it("monitors and enables stop only during a computer-use run", () => {
    const running = deriveHudState({
      wsStatus: "OPEN",
      lastCloseCode: null,
      cuaRunning: true,
      isAssistantThinking: false,
      messages: [],
    });
    expect(running.agent).toBe("monitoring");
    expect(running.capabilities.stopCopilot).toBe(true);

    const idle = deriveHudState({
      wsStatus: "OPEN",
      lastCloseCode: null,
      cuaRunning: false,
      isAssistantThinking: false,
      messages: [],
    });
    expect(idle.agent).toBe("idle");
    expect(idle.capabilities.stopCopilot).toBe(false);
  });
});
