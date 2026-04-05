import { type STTConfig, DEFAULT_STT_CONFIG } from "../models/stt.model";

export type WebSocketStatus =
  | "CONNECTING"
  | "OPEN"
  | "CLOSING"
  | "CLOSED"
  | "ERROR";

export interface STTMessageEvent {
  type: "transcript" | "partial" | "error" | "config" | "status";
  text?: string;
  isFinal?: boolean;
  message?: string;
  data?: any;
}

export interface WebSocketServiceEvents {
  open: void;
  close: { code: number; reason: string };
  error: Event;
  message: STTMessageEvent;
  statusChange: WebSocketStatus;
}

export type WSEventCallback<K extends keyof WebSocketServiceEvents> = (
  data: WebSocketServiceEvents[K],
) => void;

/**
 * Service quản lý kết nối WebSocket cho Module STT
 */
export class STTWebSocketService {
  private socket: WebSocket | null = null;
  private url: string;
  private config: STTConfig;
  private status: WebSocketStatus = "CLOSED";

  private retryCount: number = 0;
  private reconnectTimeoutId: any = null;
  private intentionToClose: boolean = false;

  private eventListeners: Partial<
    Record<
      keyof WebSocketServiceEvents,
      WSEventCallback<keyof WebSocketServiceEvents>[]
    >
  > = {};

  constructor(url: string, customConfig: Partial<STTConfig> = {}) {
    this.url = url;
    this.config = { ...DEFAULT_STT_CONFIG, ...customConfig };
  }

  /**
   * Khởi tạo kết nối WebSocket tới Server
   */
  public connect(): void {
    if (
      this.socket &&
      (this.socket.readyState === WebSocket.OPEN ||
        this.socket.readyState === WebSocket.CONNECTING)
    ) {
      console.warn("[WebSocket] Mạng đã được kết nối hoặc đang kết nối!");
      return;
    }

    this.intentionToClose = false;
    this.updateStatus("CONNECTING");

    try {
      this.socket = new WebSocket(this.url);

      this.socket.binaryType = "arraybuffer"; // Định dạng nhận và gửi Binary mặc định

      this.socket.onopen = this.handleOpen.bind(this);
      this.socket.onclose = this.handleClose.bind(this);
      this.socket.onerror = this.handleError.bind(this);
      this.socket.onmessage = this.handleMessage.bind(this);
    } catch (error) {
      this.updateStatus("ERROR");
      this.emit("error", error as Event);
    }
  }

  /**
   * Ngắt kết nối thủ công
   */
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

  /**
   * Gửi cấu hình dạng JSON lên Server (vd: session parameters, sample rate)
   */
  public sendConfig(configData: any): void {
    if (!this._isReady()) return;
    this.socket!.send(JSON.stringify({ type: "config", data: configData }));
  }

  /**
   * Gửi dữ liệu âm thanh dưới dạng Float32Array (hoặc chuyển đổi tùy theo Backend)
   * Thông thường API backend hỗ trợ trực tiếp việc nhận PCM16 hoặc Float32.
   */
  public sendAudioBuffer(buffer: Float32Array): void {
    if (!this._isReady()) return;

    // Nếu backend yêu cầu Float32 nguyên bản
    this.socket!.send(buffer.buffer);

    // *(Tip: Nếu Backend yêu cầu Int16/PCM16, ta có thể viết thêm 1 hàm Utils convert Float32 sang Int16Array ở đây trước khi gửi).*
  }

  /**
   * Gửi Text Messages hoặc Control Messages lên server
   */
  public sendMessage(payload: any): void {
    if (!this._isReady()) return;
    this.socket!.send(
      typeof payload === "string" ? payload : JSON.stringify(payload),
    );
  }

  // --- EVENTS ---

  public on<K extends keyof WebSocketServiceEvents>(
    event: K,
    callback: WSEventCallback<K>,
  ): void {
    if (!this.eventListeners[event]) {
      this.eventListeners[event] = [];
    }
    this.eventListeners[event]!.push(
      callback as WSEventCallback<keyof WebSocketServiceEvents>,
    );
  }

  public off<K extends keyof WebSocketServiceEvents>(
    event: K,
    callback: WSEventCallback<K>,
  ): void {
    if (!this.eventListeners[event]) return;
    this.eventListeners[event] = this.eventListeners[event]!.filter(
      (cb) => cb !== callback,
    );
  }

  private emit<K extends keyof WebSocketServiceEvents>(
    event: K,
    data: WebSocketServiceEvents[K],
  ): void {
    if (!this.eventListeners[event]) return;
    for (const callback of this.eventListeners[event]!) {
      callback(data);
    }
  }

  // --- INTERNAL HANDLERS ---

  private handleOpen(): void {
    this.retryCount = 0; // Reset retries
    this.updateStatus("OPEN");
    this.emit("open", undefined as any);
  }

  private handleClose(event: CloseEvent): void {
    this.socket = null;
    this.updateStatus("CLOSED");
    this.emit("close", { code: event.code, reason: event.reason });

    // Tự động kết nối lại nếu bị đứt và không phải do cố ý đóng
    if (!this.intentionToClose && this.retryCount < this.config.maxRetries) {
      this.retryCount++;
      const timeout = 1000 * Math.pow(2, this.retryCount); // Exponential backoff (2s, 4s, 8s, ...)
      console.log(
        `[WebSocket] Mất kết nối. Đang thử lại phần ${this.retryCount}/${this.config.maxRetries} sau ${timeout}ms...`,
      );

      this.reconnectTimeoutId = setTimeout(() => {
        this.connect();
      }, timeout);
    }
  }

  private handleError(event: Event): void {
    this.updateStatus("ERROR");
    this.emit("error", event);
  }

  private handleMessage(event: MessageEvent): void {
    if (typeof event.data === "string") {
      try {
        const parsed: STTMessageEvent = JSON.parse(event.data);
        this.emit("message", parsed);
      } catch (err) {
        console.warn("[WebSocket] Không thể parse JSON data:", event.data);
      }
    } else {
      // Nhận byte array (Audio phản hồi lại dạng binary, v.v.) tuỳ logic Backend
      console.log(
        "[WebSocket] Nhận dữ liệu nhị phân không xác định từ Backend",
      );
    }
  }

  private updateStatus(newStatus: WebSocketStatus): void {
    if (this.status !== newStatus) {
      this.status = newStatus;
      this.emit("statusChange", newStatus);
    }
  }

  private _isReady(): boolean {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
      console.warn("[WebSocket] Chưa rảnh hoặc kết nối đang không mở.");
      return false;
    }
    return true;
  }
}
