/**
 * WebSocket service for the /ws/chat endpoint.
 * Handles the full pipeline: text/audio input -> STT -> Agent -> LLM streaming -> TTS.
 */

export type WebSocketStatus =
  | "CONNECTING"
  | "OPEN"
  | "CLOSING"
  | "CLOSED"
  | "ERROR";

export type ImageAttachment = {
  id: string;
  dataUrl: string;
  width: number;
  height: number;
  sizeKb: number;
};

// ─── Server -> Client message types ───

export interface TranscriptMessage {
  type: "transcript";
  text: string;
  isFinal: boolean;
  data?: {
    duration?: number;
    processing_time?: number;
    language?: string;
    language_prob?: number;
    segments?: Array<{ start: number; end: number; text: string }>;
    skipped?: boolean;
    reason?: string;
  };
}

export interface AgentActionMessage {
  type: "agent_action";
  action: "tool_call" | "tool_result" | "vision_swap";
  detail: string;
  tool?: string;
  args?: Record<string, unknown>;
  result?: string;
  status?: "completed" | "error";
  timestamp: number;
}

export interface LLMTokenMessage {
  type: "llm_token";
  token: string;
  accumulated: string;
}

export interface LLMThinkingTokenMessage {
  type: "llm_thinking_token";
  token: string;
  accumulated: string;
}

export interface LLMThinkingDoneMessage {
  type: "llm_thinking_done";
  text: string;
}

export interface LLMSentenceMessage {
  type: "llm_sentence";
  text: string;
}

export interface LLMCompleteMessage {
  type: "llm_complete";
  text: string;
}

export interface TTSStartMessage {
  type: "tts_start";
  sample_rate: number;
  format: string;
}

export interface TTSEndMessage {
  type: "tts_end";
}

export interface StatusMessage {
  type: "status";
  message: string;
}

export interface ErrorMessage {
  type: "error";
  message: string;
}

export interface NotificationMessage {
  type: "notification";
  task_id: string;
  task_type: string;
  message: string;
  timestamp: number;
}

export interface CopilotStateMessage {
  type: "copilot_state";
  active: boolean;
}

export interface CopilotMessage {
  type: "copilot_message";
  text: string;
  agent_actions?: PersistedAgentAction[];
  timestamp: number;
}

export interface ScreenCaptureRequestMessage {
  type: "screen_capture_request";
  request_id: string;
  kind: "thumbnail" | "full";
  max_size: number;
}

export interface MemoryWorkerMessage {
  type: "memory_worker";
  stage: "started" | "completed" | "failed";
  timestamp: number;
  unprocessed_count?: number;
  profile_changes?: number;
  episodic_facts?: number;
  error?: string;
}

export interface PersistedAgentAction {
  action: "tool_call";
  tool: string;
  args: Record<string, unknown>;
  result?: string | null;
  status: "completed" | "error" | "running";
  timestamp: number;
}

export interface PersistedMessage {
  role: "user" | "assistant";
  content: string;
  timestamp: number;
  thinking_text?: string | null;
  agent_actions?: PersistedAgentAction[] | null;
  is_notification?: boolean;
  task_id?: string | null;
}

export interface HistoryMessage {
  type: "history";
  messages: PersistedMessage[];
}

export type ChatServerMessage =
  | TranscriptMessage
  | AgentActionMessage
  | LLMTokenMessage
  | LLMThinkingTokenMessage
  | LLMThinkingDoneMessage
  | LLMSentenceMessage
  | LLMCompleteMessage
  | TTSStartMessage
  | TTSEndMessage
  | StatusMessage
  | ErrorMessage
  | NotificationMessage
  | MemoryWorkerMessage
  | CopilotStateMessage
  | CopilotMessage
  | ScreenCaptureRequestMessage
  | HistoryMessage;

// ─── Event system ───

export interface ChatWSEvents {
  open: void;
  close: { code: number; reason: string };
  error: Event;
  message: ChatServerMessage;
  binaryMessage: ArrayBuffer;
  statusChange: WebSocketStatus;
}

export type ChatWSEventCallback<K extends keyof ChatWSEvents> = (
  data: ChatWSEvents[K],
) => void;

// ─── Service ───

export class ChatWebSocketService {
  private socket: WebSocket | null = null;
  private url: string;
  private status: WebSocketStatus = "CLOSED";
  private retryCount = 0;
  private maxRetries = 3;
  private reconnectTimeoutId: ReturnType<typeof setTimeout> | null = null;
  private intentionToClose = false;

  private eventListeners: Partial<
    Record<keyof ChatWSEvents, ChatWSEventCallback<keyof ChatWSEvents>[]>
  > = {};

  private terminalListeners: Set<(msg: any) => void> = new Set();

  public onTerminalMessage(cb: (msg: any) => void): () => void {
    this.terminalListeners.add(cb);
    return () => this.terminalListeners.delete(cb);
  }

  public sendTerminalMessage(msg: object): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(msg));
    }
  }

  constructor(url: string) {
    this.url = url;
  }

  public connect(): void {
    if (
      this.socket &&
      (this.socket.readyState === WebSocket.OPEN ||
        this.socket.readyState === WebSocket.CONNECTING)
    ) {
      return;
    }

    this.intentionToClose = false;
    this.updateStatus("CONNECTING");

    try {
      this.socket = new WebSocket(this.url);
      this.socket.binaryType = "arraybuffer";

      this.socket.onopen = this.handleOpen.bind(this);
      this.socket.onclose = this.handleClose.bind(this);
      this.socket.onerror = this.handleError.bind(this);
      this.socket.onmessage = this.handleMessage.bind(this);
    } catch {
      this.updateStatus("ERROR");
    }
  }

  public disconnect(): void {
    this.intentionToClose = true;
    if (this.reconnectTimeoutId) {
      clearTimeout(this.reconnectTimeoutId);
    }
    if (this.socket) {
      this.updateStatus("CLOSING");
      this.socket.close();
      this.socket = null;
    }
  }

  // ─── Send methods ───

  public sendUserMessage(
    text: string,
    source: "voice" | "keyboard" = "keyboard",
    images?: ImageAttachment[],
  ): void {
    if (!this.isReady()) return;
    this.socket!.send(
      JSON.stringify({
        type: "user_message",
        text,
        source,
        ...(images && images.length > 0
          ? {
              images: images.map((i) => ({
                data_url: i.dataUrl,
                width: i.width,
                height: i.height,
              })),
            }
          : {}),
      }),
    );
  }

  public sendAudioBuffer(buffer: Float32Array): void {
    if (!this.isReady()) return;
    this.socket!.send(buffer.buffer);
  }

  public sendConfig(data: Record<string, unknown>): void {
    if (!this.isReady()) return;
    this.socket!.send(JSON.stringify({ type: "config", data }));
  }

  public sendCancel(): void {
    if (!this.isReady()) return;
    this.socket!.send(JSON.stringify({ type: "cancel" }));
  }

  public sendClearMemory(): void {
    if (!this.isReady()) return;
    this.socket!.send(JSON.stringify({ type: "clear_memory" }));
  }

  public sendCopilotStart(): void {
    if (!this.isReady()) return;
    this.socket!.send(JSON.stringify({ type: "copilot_start" }));
  }

  public sendCopilotStop(): void {
    if (!this.isReady()) return;
    this.socket!.send(JSON.stringify({ type: "copilot_stop" }));
  }

  public sendScreenCaptureResponse(
    requestId: string,
    dataUrl: string | null,
    label?: string,
  ): void {
    if (!this.isReady()) return;
    this.socket!.send(
      JSON.stringify({
        type: "screen_capture_response",
        request_id: requestId,
        data_url: dataUrl,
        label: label || "",
      }),
    );
  }

  // ─── Event system ───

  public on<K extends keyof ChatWSEvents>(
    event: K,
    callback: ChatWSEventCallback<K>,
  ): void {
    if (!this.eventListeners[event]) {
      this.eventListeners[event] = [];
    }
    this.eventListeners[event]!.push(
      callback as ChatWSEventCallback<keyof ChatWSEvents>,
    );
  }

  public off<K extends keyof ChatWSEvents>(
    event: K,
    callback: ChatWSEventCallback<K>,
  ): void {
    if (!this.eventListeners[event]) return;
    this.eventListeners[event] = this.eventListeners[event]!.filter(
      (cb) => cb !== callback,
    );
  }

  private emit<K extends keyof ChatWSEvents>(
    event: K,
    data: ChatWSEvents[K],
  ): void {
    if (!this.eventListeners[event]) return;
    for (const callback of this.eventListeners[event]!) {
      callback(data);
    }
  }

  public getStatus(): WebSocketStatus {
    return this.status;
  }

  // ─── Internal handlers ───

  private handleOpen(): void {
    this.retryCount = 0;
    this.updateStatus("OPEN");
    this.emit("open", undefined as unknown as void);
  }

  private handleClose(event: CloseEvent): void {
    this.socket = null;
    this.updateStatus("CLOSED");
    this.emit("close", { code: event.code, reason: event.reason });

    // 4401 = backend says "unauthenticated at upgrade". Don't retry —
    // AuthContext / AuthGuard will route the user to /login on the next
    // 401 from any REST call (e.g. AuthContext's next /me poll).
    if (event.code === 4401) {
      console.log("[Chat WS] Closed with 4401 — auth required, not reconnecting");
      return;
    }

    if (!this.intentionToClose && this.retryCount < this.maxRetries) {
      this.retryCount++;
      const timeout = 1000 * Math.pow(2, this.retryCount);
      console.log(
        `[Chat WS] Reconnecting ${this.retryCount}/${this.maxRetries} in ${timeout}ms...`,
      );
      this.reconnectTimeoutId = setTimeout(() => this.connect(), timeout);
    }
  }

  private handleError(event: Event): void {
    this.updateStatus("ERROR");
    this.emit("error", event);
  }

  private handleMessage(event: MessageEvent): void {
    if (typeof event.data === "string") {
      try {
        const parsed = JSON.parse(event.data);
        if (typeof parsed?.type === "string" && parsed.type.startsWith("terminal_")) {
          this.terminalListeners.forEach((cb) => cb(parsed));
        } else {
          this.emit("message", parsed as ChatServerMessage);
        }
      } catch {
        console.warn("[Chat WS] Could not parse JSON:", event.data);
      }
    } else if (event.data instanceof ArrayBuffer) {
      // Binary data (TTS audio chunks)
      this.emit("binaryMessage", event.data);
    }
  }

  private updateStatus(newStatus: WebSocketStatus): void {
    if (this.status !== newStatus) {
      this.status = newStatus;
      this.emit("statusChange", newStatus);
    }
  }

  private isReady(): boolean {
    return !!this.socket && this.socket.readyState === WebSocket.OPEN;
  }
}

// ─── Singleton ───
// Shared instance used by useAssistant and useTerminal so both operate on the same socket.
import { CHAT_WS_URL } from "../constants/stt.constant";
export const chatWebsocketService = new ChatWebSocketService(CHAT_WS_URL);
export default chatWebsocketService;
