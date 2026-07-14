/**
 * WebSocket service for the /ws/chat endpoint.
 * Handles the full pipeline: text/audio input -> STT -> Agent -> LLM streaming -> TTS.
 */
import { CHAT_WS_URL } from "../constants/stt.constant";
import { getAccessToken } from "./http.service";

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

export interface PersistedImage {
  id: string;
  url: string;
  width: number;
  height: number;
  size_kb: number;
}

export interface PersistedMessage {
  role: "user" | "assistant";
  content: string;
  timestamp: number;
  thinking_text?: string | null;
  agent_actions?: PersistedAgentAction[] | null;
  is_notification?: boolean;
  task_id?: string | null;
  images?: PersistedImage[];
}

export interface ComputerUseStateMessage {
  type: "computer_use_state";
  status: "started" | "running" | "done" | "failed" | "stopped";
  goal: string;
  steps_taken: number;
  summary?: string;
  error?: string;
}

export interface ComputerUseStepElement {
  id: number;
  type: string;
  content: string;
  interactable: boolean;
}

export interface ComputerUseStepMessage {
  type: "computer_use_step";
  step: number;
  action: string;
  element_id?: number | null;
  element_content: string;
  reason: string;
  status: string;
  error?: string | null;
  som_image: string; // data URL (may be "")
  elements: ComputerUseStepElement[];
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
  | ComputerUseStateMessage
  | ComputerUseStepMessage
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
  private lastCloseCode: number | null = null;

  private eventListeners: Partial<
    Record<keyof ChatWSEvents, ChatWSEventCallback<keyof ChatWSEvents>[]>
  > = {};

  private terminalListeners: Set<(msg: unknown) => void> = new Set();

  public onTerminalMessage<T>(cb: (msg: T) => void): () => void {
    const listener = (message: unknown) => cb(message as T);
    this.terminalListeners.add(listener);
    return () => this.terminalListeners.delete(listener);
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
      const accessToken = getAccessToken();
      // Browser WebSocket does not support custom Authorization headers.
      // Send the opaque token as a subprotocol credential; the server
      // selects only the non-secret "bearer" protocol in its response.
      const socket = accessToken
        ? new WebSocket(this.url, ["bearer", accessToken])
        : new WebSocket(this.url);
      this.socket = socket;
      socket.binaryType = "arraybuffer";

      socket.onopen = () => this.handleOpen(socket);
      socket.onclose = (event) => this.handleClose(socket, event);
      socket.onerror = (event) => this.handleError(socket, event);
      socket.onmessage = (event) => this.handleMessage(socket, event);
    } catch (error) {
      this.socket = null;
      console.error("[Chat WS] Could not create WebSocket:", error);
      this.updateStatus("ERROR");
    }
  }

  public disconnect(): void {
    this.intentionToClose = true;
    this.clearReconnectTimer();
    this.disposeSocket();
    this.updateStatus("CLOSED");
  }

  public reconnect(): boolean {
    if (this.lastCloseCode === 4401) return false;
    this.intentionToClose = false;
    this.retryCount = 0;
    this.clearReconnectTimer();
    this.disposeSocket();
    this.updateStatus("CLOSED");
    this.connect();
    return this.status === "CONNECTING" || this.status === "OPEN";
  }

  public getLastCloseCode(): number | null {
    return this.lastCloseCode;
  }

  // ─── Send methods ───

  public sendUserMessage(
    text: string,
    source: "voice" | "keyboard" = "keyboard",
    images?: ImageAttachment[],
  ): boolean {
    if (!this.isReady()) return false;
    try {
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
      return true;
    } catch (error) {
      console.error("[Chat WS] Failed to send user message:", error);
      return false;
    }
  }

  public sendAudioBuffer(buffer: Float32Array): void {
    if (!this.isReady()) return;
    this.socket!.send(buffer.buffer);
  }

  public sendConfig(data: Record<string, unknown>): void {
    if (!this.isReady()) return;
    this.socket!.send(JSON.stringify({ type: "config", data }));
  }

  public sendCancel(): boolean {
    if (!this.isReady()) return false;
    try {
      this.socket!.send(JSON.stringify({ type: "cancel" }));
      return true;
    } catch (error) {
      console.error("[Chat WS] Failed to send cancellation:", error);
      return false;
    }
  }

  public sendClearMemory(): void {
    if (!this.isReady()) return;
    this.socket!.send(JSON.stringify({ type: "clear_memory" }));
  }

  public sendCopilotStart(): void {
    if (!this.isReady()) return;
    this.socket!.send(JSON.stringify({ type: "copilot_start" }));
  }

  public sendCopilotStop(): boolean {
    if (!this.isReady()) return false;
    try {
      this.socket!.send(JSON.stringify({ type: "copilot_stop" }));
      return true;
    } catch (error) {
      console.error("[Chat WS] Failed to stop Co-pilot:", error);
      return false;
    }
  }



  public sendComputerUseStop(): void {
    if (!this.isReady()) return;
    this.socket!.send(JSON.stringify({ type: "computer_use_stop" }));
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

  private handleOpen(socket: WebSocket): void {
    if (this.socket !== socket) return;
    this.retryCount = 0;
    this.lastCloseCode = null;
    this.updateStatus("OPEN");
    this.emit("open", undefined as unknown as void);
  }

  private handleClose(socket: WebSocket, event: CloseEvent): void {
    if (this.socket !== socket) return;
    this.socket = null;
    this.lastCloseCode = event.code;
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
      this.reconnectTimeoutId = setTimeout(() => {
        this.reconnectTimeoutId = null;
        this.connect();
      }, timeout);
    }
  }

  private handleError(socket: WebSocket, event: Event): void {
    if (this.socket !== socket) return;
    this.updateStatus("ERROR");
    this.emit("error", event);
  }

  private handleMessage(socket: WebSocket, event: MessageEvent): void {
    if (this.socket !== socket) return;
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

  private clearReconnectTimer(): void {
    if (!this.reconnectTimeoutId) return;
    clearTimeout(this.reconnectTimeoutId);
    this.reconnectTimeoutId = null;
  }

  private disposeSocket(): void {
    const socket = this.socket;
    if (!socket) return;
    this.socket = null;
    this.updateStatus("CLOSING");
    socket.onopen = null;
    socket.onclose = null;
    socket.onerror = null;
    socket.onmessage = null;
    socket.close();
  }
}

// ─── Singleton ───
// Shared instance used by useAssistant and useTerminal so both operate on the same socket.
export const chatWebsocketService = new ChatWebSocketService(CHAT_WS_URL);
export default chatWebsocketService;
