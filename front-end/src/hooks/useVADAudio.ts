import { useState, useEffect, useRef, useCallback } from "react";
import { createVAD, VAD } from "../services/vad.service";
import { float32ToWav } from "../utils/audio.util";

export interface VADEventLog {
  id: string;
  duration: number;
  timestamp: Date;
  audioUrl?: string;
}

export function useVADAudio() {
  const [isLoaded, setIsLoaded] = useState(false);
  const [statusMessage, setStatusMessage] = useState("Khởi tạo...");
  const [isRecording, setIsRecording] = useState(false);
  const isRecordingRef = useRef(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [vadScore, setVadScore] = useState(0);
  const [eventLogs, setEventLogs] = useState<VADEventLog[]>([]);
  const volumeRef = useRef(0);

  const vadRef = useRef<VAD | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);

  // Khởi tạo Model VAD khi Hook được mount
  useEffect(() => {
    let isMounted = true;

    async function init() {
      try {
        setStatusMessage("Đang tải mô hình VAD (~15MB Lần đầu)...");
        const vadInstance = await createVAD();

        if (!isMounted) return;
        vadRef.current = vadInstance;

        // Gán các Event Listeners
        vadInstance.on("status", (e) => setStatusMessage(e.message));
        vadInstance.on("speech-start", () => setIsSpeaking(true));
        vadInstance.on("speech-end", () => setIsSpeaking(false));
        vadInstance.on("debug", (e) => {
          if (e.message === "VAD score" && e.data) {
            setVadScore((e.data as any).probability || 0);
          }
        });
        vadInstance.on("speech-ready", (e) => {
          const wavBlob = float32ToWav(e.buffer, 16000);
          const audioUrl = URL.createObjectURL(wavBlob);

          setEventLogs((prev) => [
            {
              id: Math.random().toString(36).substring(7),
              duration: e.duration,
              timestamp: new Date(),
              audioUrl,
            },
            ...prev,
          ]);
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
      // Dọn dẹp nếu có hàm destroy (Chưa thiết kế bên dịch vụ)
    };
  }, []);

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
            channelCount: 1, // Mono
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
          },
        });

        streamRef.current = stream;

        // Ép chuẩn 16000Hz (Bắt buộc cho Whisper/Silero)
        const AudioContextCtor =
          window.AudioContext || (window as any).webkitAudioContext;
        const audioContext = new AudioContextCtor({ sampleRate: 16000 });
        audioContextRef.current = audioContext;

        const source = audioContext.createMediaStreamSource(stream);
        sourceRef.current = source;

        // Silero VAD Model yêu cầu chính xác 512 samples ở 16kHz cho mỗi Inference step!
        // Việc dùng 4096 sẽ làm đầu vào bị sai ma trận (LSTM Shape Error)
        const processor = audioContext.createScriptProcessor(512, 1, 1);
        processorRef.current = processor;

        source.connect(processor);
        // Thêm GainNode với âm lượng = 0 để tránh bị vọng âm (feedback loop)
        // Khi bị dội âm, browser có thể tự ngắt sạch dữ liệu khiến buffer trả về toàn số 0.
        const dummyGain = audioContext.createGain();
        dummyGain.gain.value = 0;
        processor.connect(dummyGain);
        dummyGain.connect(audioContext.destination);

        processor.onaudioprocess = (e) => {
          if (!isRecordingRef.current) return;

          // Lấy dữ liệu mảng gốc Float32
          // Browser sẽ liên tục ghi đè vào mảng gốc gây loãng tần số khi chạy Async
          // => Bắt buộc phải tạo bản Clone cứng bằng new Float32Array()
          const inputBuffer = new Float32Array(e.inputBuffer.getChannelData(0));

          // Tính toán Volume thủ công tránh re-render React liên tục
          let maxVal = 0;
          for (let i = 0; i < inputBuffer.length; i++) {
            const val = inputBuffer[i];
            if (val > maxVal) maxVal = val;
            else if (-val > maxVal) maxVal = -val;
          }
          volumeRef.current = maxVal;

          // Bơm vào VAD Model
          vadRef.current?.processAudio(inputBuffer);
        };

        isRecordingRef.current = true;
        setIsRecording(true);
        setStatusMessage("Đang lắng nghe...");
      } catch (err: any) {
        console.error("Không thể truy cập Microphone:", err);
        setStatusMessage("Lỗi Microphone: Bị từ chối thiết bị");
      }
    },
    [isRecording],
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

  // Đảm bảo cleanup thiết bị khi Unmount
  useEffect(() => {
    return () => {
      if (isRecording) {
        stopRecording();
      }
    };
  }, [isRecording, stopRecording]);

  return {
    isLoaded,
    isRecording,
    isSpeaking,
    vadScore,
    statusMessage,
    eventLogs,
    volumeRef,
    startRecording,
    stopRecording,
  };
}
