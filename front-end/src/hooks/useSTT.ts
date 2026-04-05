import { useState, useEffect, useRef, useCallback } from "react";
import { createVAD, VAD } from "../services/vad.service";
import {
  STTWebSocketService,
  type STTMessageEvent,
  type WebSocketStatus,
} from "../services/websocket.service";
import { float32ToWav } from "../utils/audio.util";
import { STT_WS_URL, STT_DEFAULT_LANGUAGE } from "../constants/stt.constant";

// ─── Types ───

export interface STTTranscript {
  id: string;
  text: string;
  isFinal: boolean;
  language?: string;
  languageProb?: number;
  processingTime?: number;
  audioDuration?: number;
  audioUrl?: string;
  timestamp: Date;
}

export interface UseSTTReturn {
  // VAD state
  isLoaded: boolean;
  isRecording: boolean;
  isSpeaking: boolean;
  vadScore: number;
  statusMessage: string;
  volumeRef: React.RefObject<number>;

  // WebSocket state
  wsStatus: WebSocketStatus;
  isConnected: boolean;

  // STT results
  transcripts: STTTranscript[];

  // Language/Model config
  language: string;
  setLanguage: (lang: string) => void;
  modelSize: string;
  setModelSize: (size: string) => void;

  // Controls
  startRecording: (deviceId?: string) => void;
  stopRecording: () => void;
  connectWS: () => void;
  disconnectWS: () => void;
}

// ─── Hook ───

export function useSTT(): UseSTTReturn {
  // ── VAD State ──
  const [isLoaded, setIsLoaded] = useState(false);
  const [statusMessage, setStatusMessage] = useState("Khởi tạo...");
  const [isRecording, setIsRecording] = useState(false);
  const isRecordingRef = useRef(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [vadScore, setVadScore] = useState(0);
  const volumeRef = useRef(0);

  // ── WebSocket State ──
  const [wsStatus, setWsStatus] = useState<WebSocketStatus>("CLOSED");
  const [language, setLanguage] = useState(STT_DEFAULT_LANGUAGE);
  const [modelSize, setModelSize] = useState<string>("base");

  // ── STT Results ──
  const [transcripts, setTranscripts] = useState<STTTranscript[]>([]);

  // ── Refs ──
  const vadRef = useRef<VAD | null>(null);
  const wsRef = useRef<STTWebSocketService | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const languageRef = useRef(STT_DEFAULT_LANGUAGE);
  const modelSizeRef = useRef("base");

  // Map để theo dõi pending transcript (audio đã gửi, chờ kết quả)
  const pendingMapRef = useRef<
    Map<string, { audioUrl?: string; timestamp: Date }>
  >(new Map());

  // Đếm thứ tự gửi để map response
  const sendQueueRef = useRef<string[]>([]);

  // Sync refs để callback closure luôn đúng
  useEffect(() => {
    languageRef.current = language;
  }, [language]);

  useEffect(() => {
    modelSizeRef.current = modelSize;
  }, [modelSize]);

  // ── Khởi tạo VAD Model ──
  useEffect(() => {
    let isMounted = true;

    async function init() {
      try {
        setStatusMessage("Đang tải mô hình VAD (~15MB Lần đầu)...");
        const vadInstance = await createVAD();

        if (!isMounted) return;
        vadRef.current = vadInstance;

        // VAD Events
        vadInstance.on("status", (e) => setStatusMessage(e.message));
        vadInstance.on("speech-start", () => setIsSpeaking(true));
        vadInstance.on("speech-end", () => setIsSpeaking(false));
        vadInstance.on("debug", (e) => {
          if (e.message === "VAD score" && e.data) {
            setVadScore((e.data as any).probability || 0);
          }
        });

        // ★ Core Integration: Khi VAD phát hiện speech xong → gửi lên Backend
        vadInstance.on("speech-ready", (e) => {
          const wavBlob = float32ToWav(e.buffer, 16000);
          const audioUrl = URL.createObjectURL(wavBlob);

          const id = Date.now().toString(36) + Math.random().toString(36).slice(2, 7);

          // Lưu pending info
          pendingMapRef.current.set(id, {
            audioUrl,
            timestamp: new Date(),
          });
          sendQueueRef.current.push(id);

          // Tạo transcript placeholder (processing)
          setTranscripts((prev) => [
            ...prev,
            {
              id,
              text: "",
              isFinal: false,
              audioUrl,
              audioDuration: e.duration,
              timestamp: new Date(),
            },
          ]);

          // Gửi Float32Array buffer qua WebSocket nếu đang kết nối
          if (wsRef.current) {
            wsRef.current.sendAudioBuffer(e.buffer);
          }
        });

        setIsLoaded(true);
        setStatusMessage("Sẵn sàng");
      } catch (err: any) {
        if (isMounted) setStatusMessage(`Lỗi khởi tạo: ${err.message}`);
      }
    }

    init();

    return () => {
      isMounted = false;
    };
  }, []);

  // ── Khởi tạo WebSocket Service ──
  useEffect(() => {
    const ws = new STTWebSocketService(STT_WS_URL);
    wsRef.current = ws;

    ws.on("statusChange", (status) => {
      setWsStatus(status);
    });

    ws.on("open", () => {
      // Gửi config session khi kết nối thành công
      ws.sendConfig({
        language: languageRef.current,
        model_size: modelSizeRef.current,
        sample_rate: 16000,
      });
    });

    ws.on("message", (msg: STTMessageEvent) => {
      if (msg.type === "status") {
        setStatusMessage(msg.message || "");
      }

      if (msg.type === "transcript") {
        // Lấy ID pending tiếp theo trong queue
        const pendingId = sendQueueRef.current.shift();

        if (pendingId && pendingMapRef.current.has(pendingId)) {
          pendingMapRef.current.delete(pendingId);

          // Cập nhật transcript placeholder → kết quả thật
          setTranscripts((prev) =>
            prev.map((t) =>
              t.id === pendingId
                ? {
                    ...t,
                    text: msg.text || "",
                    isFinal: msg.isFinal ?? true,
                    language: msg.data?.language,
                    languageProb: msg.data?.language_prob,
                    processingTime: msg.data?.processing_time,
                    audioDuration: msg.data?.duration
                      ? msg.data.duration * 1000
                      : t.audioDuration,
                  }
                : t,
            ),
          );
        } else {
          // Fallback: Không tìm thấy pending, tạo entry mới
          if (msg.text && msg.text.trim()) {
            setTranscripts((prev) => [
              ...prev,
              {
                id:
                  Date.now().toString(36) +
                  Math.random().toString(36).slice(2, 7),
                text: msg.text || "",
                isFinal: msg.isFinal ?? true,
                language: msg.data?.language,
                languageProb: msg.data?.language_prob,
                processingTime: msg.data?.processing_time,
                audioDuration: msg.data?.duration
                  ? msg.data.duration * 1000
                  : undefined,
                timestamp: new Date(),
              },
            ]);
          }
        }
      }

      if (msg.type === "error") {
        console.error("[STT WS] Server error:", msg.message);
        setStatusMessage(`Error: ${msg.message}`);
      }
    });

    ws.on("error", () => {
      console.error("[STT WS] Connection error");
    });

    // Auto-connect
    ws.connect();

    return () => {
      ws.disconnect();
      wsRef.current = null;
    };
  }, []);

  // ── Gửi config update khi language hoặc model thay đổi ──
  useEffect(() => {
    if (wsRef.current && wsStatus === "OPEN") {
      wsRef.current.sendConfig({
        language,
        model_size: modelSize,
        sample_rate: 16000,
      });
    }
  }, [language, modelSize, wsStatus]);

  // ── Controls ──

  const startRecording = useCallback(
    async (deviceId?: string) => {
      if (!vadRef.current || !vadRef.current.isReady) {
        alert("Vui lòng đợi VAD Model tải xong!");
        return;
      }

      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            deviceId: deviceId ? { exact: deviceId } : undefined,
            channelCount: 1,
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
          },
        });

        streamRef.current = stream;

        const AudioContextCtor =
          window.AudioContext || (window as any).webkitAudioContext;
        const audioContext = new AudioContextCtor({ sampleRate: 16000 });
        audioContextRef.current = audioContext;

        const source = audioContext.createMediaStreamSource(stream);
        sourceRef.current = source;

        // Silero VAD yêu cầu chính xác 512 samples ở 16kHz
        const processor = audioContext.createScriptProcessor(512, 1, 1);
        processorRef.current = processor;

        source.connect(processor);

        // Dummy gain node để tránh feedback loop
        const dummyGain = audioContext.createGain();
        dummyGain.gain.value = 0;
        processor.connect(dummyGain);
        dummyGain.connect(audioContext.destination);

        processor.onaudioprocess = (e) => {
          if (!isRecordingRef.current) return;

          const inputBuffer = new Float32Array(
            e.inputBuffer.getChannelData(0),
          );

          // Tính volume
          let maxVal = 0;
          for (let i = 0; i < inputBuffer.length; i++) {
            const val = inputBuffer[i];
            if (val > maxVal) maxVal = val;
            else if (-val > maxVal) maxVal = -val;
          }
          volumeRef.current = maxVal;

          // Bơm vào VAD
          vadRef.current?.processAudio(inputBuffer);
        };

        isRecordingRef.current = true;
        setIsRecording(true);
        setStatusMessage("Đang lắng nghe...");

        // Auto-connect WS nếu chưa kết nối
        if (wsRef.current && wsStatus === "CLOSED") {
          wsRef.current.connect();
        }
      } catch (err: any) {
        console.error("Không thể truy cập Microphone:", err);
        setStatusMessage("Lỗi Microphone: Bị từ chối thiết bị");
      }
    },
    [wsStatus],
  );

  const stopRecording = useCallback(() => {
    if (processorRef.current && sourceRef.current && audioContextRef.current) {
      processorRef.current.disconnect();
      sourceRef.current.disconnect();
      audioContextRef.current.close().catch(console.error);
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
    }

    processorRef.current = null;
    sourceRef.current = null;
    audioContextRef.current = null;
    streamRef.current = null;

    setIsRecording(false);
    isRecordingRef.current = false;
    setIsSpeaking(false);
    setVadScore(0);
    setStatusMessage("Đã ngừng thu âm");
  }, []);

  const connectWS = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.connect();
    }
  }, []);

  const disconnectWS = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.disconnect();
    }
  }, []);

  // Cleanup khi unmount
  useEffect(() => {
    return () => {
      if (isRecordingRef.current) {
        stopRecording();
      }
    };
  }, [stopRecording]);

  return {
    // VAD
    isLoaded,
    isRecording,
    isSpeaking,
    vadScore,
    statusMessage,
    volumeRef,

    // WebSocket
    wsStatus,
    isConnected: wsStatus === "OPEN",

    // STT
    transcripts,

    // Language/Model
    language,
    setLanguage,
    modelSize,
    setModelSize,

    // Controls
    startRecording,
    stopRecording,
    connectWS,
    disconnectWS,
  };
}
