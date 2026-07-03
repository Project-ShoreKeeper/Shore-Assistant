import { describe, expect, it, vi } from "vitest";

import {
  HudActionDeduplicator,
  reduceHudPending,
  validateHudAction,
  type HudAction,
} from "./hud-actions";

const cancelAction: HudAction = {
  requestId: "request-1",
  version: 1,
  action: "cancel_generation",
};

describe("validateHudAction", () => {
  it("trims and accepts a bounded prompt", () => {
    const parsed = validateHudAction({
      requestId: "request-1",
      version: 1,
      action: "send_prompt",
      payload: { text: "  hello  " },
    });

    expect(parsed).toEqual({
      ok: true,
      action: {
        requestId: "request-1",
        version: 1,
        action: "send_prompt",
        payload: { text: "hello" },
      },
    });
  });

  it("rejects unknown versions with an acknowledgement", () => {
    expect(validateHudAction({
      requestId: "request-1",
      version: 2,
      action: "cancel_generation",
    })).toEqual({
      ok: false,
      result: {
        requestId: "request-1",
        ok: false,
        error: "invalid",
        message: "Unsupported HUD action version.",
      },
    });
  });

  it("does not acknowledge an invalid request ID", () => {
    expect(validateHudAction({
      requestId: "",
      version: 1,
      action: "cancel_generation",
    })).toEqual({
      ok: false,
      result: null,
    });
  });

  it("rejects unexpected payload keys", () => {
    const parsed = validateHudAction({
      ...cancelAction,
      payload: { arbitrary: true },
    });
    expect(parsed.ok).toBe(false);
  });
});

describe("HudActionDeduplicator", () => {
  it("executes concurrent duplicate requests once", async () => {
    const deduplicator = new HudActionDeduplicator();
    const executor = vi.fn(async () => ({ ok: true }));

    const first = deduplicator.run(cancelAction, executor, 1_000);
    const duplicate = deduplicator.run(cancelAction, executor, 1_001);

    await expect(first).resolves.toEqual({
      requestId: "request-1",
      ok: true,
    });
    await expect(duplicate).resolves.toEqual({
      requestId: "request-1",
      ok: true,
    });
    expect(executor).toHaveBeenCalledTimes(1);
  });

  it("allows a request ID again after the TTL", async () => {
    const deduplicator = new HudActionDeduplicator(100, 100);
    const executor = vi.fn(async () => ({ ok: true }));

    await deduplicator.run(cancelAction, executor, 1_000);
    await deduplicator.run(cancelAction, executor, 1_101);

    expect(executor).toHaveBeenCalledTimes(2);
  });
});

describe("reduceHudPending", () => {
  it("adds, settles and expires requests", () => {
    const started = reduceHudPending({}, {
      type: "started",
      requestId: "one",
      action: "send_prompt",
      now: 1_000,
    });
    const two = reduceHudPending(started, {
      type: "started",
      requestId: "two",
      action: "retry_connection",
      now: 4_000,
    });

    expect(reduceHudPending(two, {
      type: "expired",
      now: 6_001,
      timeoutMs: 5_000,
    })).toEqual({
      two: { action: "retry_connection", startedAt: 4_000 },
    });
    expect(reduceHudPending(two, {
      type: "settled",
      requestId: "one",
    })).not.toHaveProperty("one");
  });
});
