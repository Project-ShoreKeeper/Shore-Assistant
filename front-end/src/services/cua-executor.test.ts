import { beforeEach, describe, expect, it, vi } from "vitest";

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: invokeMock }));
vi.mock("@Shore/utils/tauri.util", () => ({ isTauri: () => true }));
vi.mock("./screen-capture.service", () => ({
  isScreenSharing: () => true,
  captureFrameDataUrl: vi
    .fn()
    .mockResolvedValue("data:image/jpeg;base64,AA=="),
}));

import { announceCuaReady, executeCuaStep } from "./cua-executor.service";

describe("executeCuaStep", () => {
  beforeEach(() => {
    invokeMock.mockReset();
    vi.stubGlobal("window", { screen: { width: 1440, height: 900 } });
  });

  it("executes the action then replies with a fresh frame", async () => {
    invokeMock.mockResolvedValue(undefined);
    const sent: object[] = [];
    await executeCuaStep(
      {
        request_id: "r1",
        action: { func: "click", x: 10, y: 20 },
        display_hint: "Click OK",
      },
      (message) => sent.push(message),
      0,
    );
    expect(invokeMock).toHaveBeenCalledWith("input_execute", {
      action: { func: "click", x: 10, y: 20 },
    });
    expect(sent[0]).toMatchObject({
      request_id: "r1",
      screenshot: "data:image/jpeg;base64,AA==",
      screen: { width: 1440, height: 900 },
    });
  });

  it("reports executor errors instead of a screenshot", async () => {
    invokeMock.mockRejectedValue("accessibility-denied: no permission");
    const sent: Array<Record<string, unknown>> = [];
    await executeCuaStep(
      {
        request_id: "r2",
        action: { func: "click", x: 1, y: 1 },
        display_hint: "",
      },
      (message) => sent.push(message as Record<string, unknown>),
      0,
    );
    expect(sent[0].error).toContain("accessibility-denied");
  });
});

describe("announceCuaReady", () => {
  beforeEach(() => {
    vi.stubGlobal("window", { screen: { width: 1440, height: 900 } });
  });

  it("sends cua_ready with the logical screen size", async () => {
    const sent: object[] = [];
    await announceCuaReady((screen) => sent.push(screen));
    expect(sent[0]).toEqual({ width: 1440, height: 900 });
  });
});
