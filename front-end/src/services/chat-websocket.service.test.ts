import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChatWebSocketService } from "./chat-websocket.service";

class FakeWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;
  static instances: FakeWebSocket[] = [];

  readonly url: string;
  readonly protocols?: string | string[];
  readyState = FakeWebSocket.CONNECTING;
  binaryType: BinaryType = "blob";
  onopen: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  sent: string[] = [];

  constructor(url: string | URL, protocols?: string | string[]) {
    this.url = String(url);
    this.protocols = protocols;
    FakeWebSocket.instances.push(this);
  }

  send(data: string | ArrayBufferLike | Blob | ArrayBufferView): void {
    this.sent.push(String(data));
  }

  close(): void {
    this.readyState = FakeWebSocket.CLOSED;
  }

  open(): void {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.(new Event("open"));
  }

  serverClose(code: number): void {
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.({ code, reason: "" } as CloseEvent);
  }
}

describe("ChatWebSocketService reconnect", () => {
  beforeEach(() => {
    FakeWebSocket.instances = [];
    vi.stubGlobal("WebSocket", FakeWebSocket);
  });

  it("ignores delayed events from the socket replaced by manual reconnect", () => {
    const service = new ChatWebSocketService("ws://example.test/chat");
    service.connect();
    const stale = FakeWebSocket.instances[0];
    const staleClose = stale.onclose;

    expect(service.reconnect()).toBe(true);
    const current = FakeWebSocket.instances[1];
    current.open();
    staleClose?.({ code: 1006, reason: "" } as CloseEvent);

    expect(service.getStatus()).toBe("OPEN");
    expect(FakeWebSocket.instances).toHaveLength(2);
  });

  it("never reconnects an authentication close", () => {
    vi.useFakeTimers();
    const service = new ChatWebSocketService("ws://example.test/chat");
    service.connect();
    FakeWebSocket.instances[0].serverClose(4401);

    expect(service.getLastCloseCode()).toBe(4401);
    expect(service.reconnect()).toBe(false);
    vi.runAllTimers();
    expect(FakeWebSocket.instances).toHaveLength(1);
    vi.useRealTimers();
  });

  it("sends a user message only on an open socket", () => {
    const service = new ChatWebSocketService("ws://example.test/chat");
    service.connect();
    const socket = FakeWebSocket.instances[0];

    expect(service.sendUserMessage("hello")).toBe(false);
    socket.open();
    expect(service.sendUserMessage("hello")).toBe(true);
    expect(JSON.parse(socket.sent[0])).toMatchObject({
      type: "user_message",
      text: "hello",
    });
  });
});
