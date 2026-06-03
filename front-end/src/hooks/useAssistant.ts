import { useState, useEffect, useRef, useCallback } from "react";
import { createVAD, VAD } from "../services/vad.service";
import {
  chatWebsocketService,
  type ChatWebSocketService,
  type WebSocketStatus,
  type ChatServerMessage,
  type ImageAttachment,
} from "../services/chat-websocket.service";
import { float32ToWav } from "../utils/audio.util";
import { TTSPlayer } from "../utils/tts-player.util";
import { STT_DEFAULT_LANGUAGE } from "../constants/stt.constant";

// ─── Types ───

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  thinkingText?: string;
  isThinkingPhase?: boolean;
  audioUrl?: string;
  isStreaming?: boolean;
  isNotification?: boolean;
  taskId?: string;
  timestamp: Date;
  agentActions?: AgentAction[];
  images?: ImageAttachment[];
}

export interface AgentAction {
  id: string;
  action: "tool_call" | "tool_result";
  detail: string;
  tool?: string;
  args?: Record<string, unknown>;
  result?: string;
  status: "running" | "completed" | "error";
  timestamp: Date;
}

export interface UseAssistantReturn {
  // VAD state
  isVADLoaded: boolean;
  isRecording: boolean;
  isSpeaking: boolean;
  volumeRef: React.RefObject<number>;

  // Connection
  wsStatus: WebSocketStatus;
  isConnected: boolean;

  messages: ChatMessage[];
  isAssistantThinking: boolean;
  isAssistantSpeaking: boolean;

  // Settings
  language: string;
  setLanguage: (lang: string) => void;
  thinkingEnabled: boolean;
  setThinkingEnabled: (enabled: boolean) => void;

  // Controls
  startRecording: (deviceId?: string) => void;
  stopRecording: () => void;
  sendTextMessage: (text: string, images?: ImageAttachment[]) => void;
  cancelGeneration: () => void;
  clearMessages: () => void;
}

// ─── Hook ───

export function useAssistant(): UseAssistantReturn {
  // VAD state
  const [isVADLoaded, setIsVADLoaded] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const isRecordingRef = useRef(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const volumeRef = useRef(0);

  // WebSocket state
  const [wsStatus, setWsStatus] = useState<WebSocketStatus>("CLOSED");
  const [language, setLanguage] = useState(STT_DEFAULT_LANGUAGE);
  const languageRef = useRef(STT_DEFAULT_LANGUAGE);
  const [thinkingEnabled, setThinkingEnabled] = useState(false);
  const thinkingEnabledRef = useRef(false);

  // Conversation state
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isAssistantThinking, setIsAssistantThinking] = useState(false);
  const [isAssistantSpeaking, setIsAssistantSpeaking] = useState(false);

  // The ID of the currently streaming assistant message
  const streamingMsgIdRef = useRef<string | null>(null);

  // TTS Player
  const ttsPlayerRef = useRef<TTSPlayer | null>(null);

  // Refs
  const vadRef = useRef<VAD | null>(null);
  const wsRef = useRef<ChatWebSocketService | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);

  useEffect(() => {
    languageRef.current = language;
  }, [language]);

  useEffect(() => {
    thinkingEnabledRef.current = thinkingEnabled;
  }, [thinkingEnabled]);

  // ── Initialize VAD ──
  useEffect(() => {
    let isMounted = true;

    async function init() {
      try {
        const vadInstance = await createVAD();
        if (!isMounted) return;
        vadRef.current = vadInstance;

        vadInstance.on("speech-start", () => setIsSpeaking(true));
        vadInstance.on("speech-end", () => setIsSpeaking(false));

        vadInstance.on("speech-ready", (e) => {
          // Create audio URL for playback
          const wavBlob = float32ToWav(e.buffer, 16000);
          const audioUrl = URL.createObjectURL(wavBlob);

          // Add user message placeholder (will be updated with transcript)
          const id =
            Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
          setMessages((prev) => [
            ...prev,
            {
              id,
              role: "user",
              text: "",
              audioUrl,
              isStreaming: true,
              timestamp: new Date(),
            },
          ]);

          // Stop any ongoing TTS before sending new input
          if (ttsPlayerRef.current) {
            ttsPlayerRef.current.stop();
            ttsPlayerRef.current = null;
            setIsAssistantSpeaking(false);
          }

          // Send audio to backend
          if (wsRef.current) {
            wsRef.current.sendAudioBuffer(e.buffer);
          }
        });

        setIsVADLoaded(true);
      } catch (err) {
        console.error("VAD init error:", err);
      }
    }

    init();
    return () => {
      isMounted = false;
    };
  }, []);

  // ── Initialize Chat WebSocket ──
  useEffect(() => {
    const ws = chatWebsocketService;
    wsRef.current = ws;

    const handleStatusChange = (status: WebSocketStatus) => setWsStatus(status);

    const handleOpen = () => {
      ws.sendConfig({
        language: languageRef.current,
        thinking: thinkingEnabledRef.current,
      });
    };

    const handleMessage = (msg: ChatServerMessage) => {
      switch (msg.type) {
        case "history": {
          const rand = () => Math.random().toString(36).slice(2, 7);
          const hydrated: ChatMessage[] = msg.messages.map((m) => {
            const actions: AgentAction[] = (m.agent_actions || []).map((a) => ({
              id: `hist-act-${a.timestamp}-${rand()}`,
              action: a.action,
              detail: "",
              tool: a.tool,
              args: a.args,
              result: a.result ?? undefined,
              status: a.status,
              timestamp: new Date(a.timestamp * 1000),
            }));
            return {
              id: `hist-${m.timestamp}-${rand()}`,
              role: m.role,
              text: m.content,
              thinkingText: m.thinking_text || undefined,
              isThinkingPhase: false,
              isStreaming: false,
              isNotification: m.is_notification || false,
              taskId: m.task_id || undefined,
              timestamp: new Date(m.timestamp * 1000),
              agentActions: actions.length > 0 ? actions : undefined,
            };
          });
          setMessages(hydrated);
          break;
        }

        case "transcript": {
          if (msg.data?.skipped) break;
          const text = msg.text || "";
          // Update the last user message that's still streaming (voice input)
          setMessages((prev) => {
            const lastStreamingUserIdx = prev.findLastIndex(
              (m) => m.role === "user" && m.isStreaming,
            );
            if (lastStreamingUserIdx >= 0) {
              const updated = [...prev];
              updated[lastStreamingUserIdx] = {
                ...updated[lastStreamingUserIdx],
                text,
                isStreaming: false,
              };
              // Add a streaming assistant placeholder so the "Thinking..."
              // indicator appears immediately while waiting for the first token.
              if (text.trim()) {
                const placeholderId =
                  Date.now().toString(36) +
                  Math.random().toString(36).slice(2, 7);
                streamingMsgIdRef.current = placeholderId;
                updated.push({
                  id: placeholderId,
                  role: "assistant",
                  text: "",
                  isStreaming: true,
                  timestamp: new Date(),
                });
              }
              return updated;
            }
            return prev;
          });
          if (text.trim()) {
            setIsAssistantThinking(true);
          }
          break;
        }

        case "agent_action": {
          if (msg.action === "tool_call") {
            const actionItem: AgentAction = {
              id: Date.now().toString(36) + Math.random().toString(36).slice(2, 7),
              action: "tool_call",
              detail: msg.detail,
              tool: msg.tool,
              args: msg.args,
              status: "running",
              timestamp: new Date(msg.timestamp * 1000),
            };

            setMessages((prev) => {
              const lastMsg = prev[prev.length - 1];
              if (lastMsg?.role === "assistant" && lastMsg.isStreaming) {
                const updated = [...prev];
                // Clear any pre-tool-call text so round-2 tokens stream into
                // a clean bubble (avoids "Let me check..." being awkwardly
                // overwritten character-by-character by the post-tool answer).
                updated[updated.length - 1] = {
                  ...lastMsg,
                  text: "",
                  agentActions: [...(lastMsg.agentActions || []), actionItem],
                };
                return updated;
              } else {
                const id = Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
                streamingMsgIdRef.current = id;
                return [
                  ...prev,
                  {
                    id,
                    role: "assistant",
                    text: "",
                    isStreaming: true,
                    timestamp: new Date(),
                    agentActions: [actionItem],
                  },
                ];
              }
            });

            setIsAssistantThinking(true);
          } else if (msg.action === "tool_result") {
            const isError =
              msg.status === "error" || (msg.result?.startsWith("Error") ?? false);

            setMessages((prev) => {
              const lastMsg = prev[prev.length - 1];
              if (
                lastMsg?.role === "assistant" &&
                lastMsg.isStreaming &&
                lastMsg.agentActions
              ) {
                const updated = [...prev];
                const updatedActions = [...lastMsg.agentActions];
                const runningIdx = updatedActions.findLastIndex(
                  (a) => a.status === "running" && a.tool === msg.tool,
                );
                if (runningIdx >= 0) {
                  updatedActions[runningIdx] = {
                    ...updatedActions[runningIdx],
                    result: msg.result,
                    status: isError ? "error" : "completed",
                  };
                }
                updated[updated.length - 1] = {
                  ...lastMsg,
                  agentActions: updatedActions,
                };
                return updated;
              }
              return prev;
            });
          }
          break;
        }

        case "llm_thinking_token": {
          // Stream thinking tokens into the assistant message's thinkingText
          setMessages((prev) => {
            const lastMsg = prev[prev.length - 1];
            if (lastMsg?.role === "assistant" && lastMsg.isStreaming) {
              const updated = [...prev];
              updated[updated.length - 1] = {
                ...lastMsg,
                thinkingText: msg.accumulated,
                isThinkingPhase: true,
              };
              return updated;
            } else {
              // Create new assistant message in thinking phase
              const id =
                Date.now().toString(36) +
                Math.random().toString(36).slice(2, 7);
              streamingMsgIdRef.current = id;
              return [
                ...prev,
                {
                  id,
                  role: "assistant",
                  text: "",
                  thinkingText: msg.accumulated,
                  isThinkingPhase: true,
                  isStreaming: true,
                  timestamp: new Date(),
                },
              ];
            }
          });
          break;
        }

        case "llm_thinking_done": {
          // Mark thinking phase as complete
          setMessages((prev) => {
            const lastMsg = prev[prev.length - 1];
            if (lastMsg?.role === "assistant" && lastMsg.isStreaming) {
              const updated = [...prev];
              updated[updated.length - 1] = {
                ...lastMsg,
                thinkingText: msg.text,
                isThinkingPhase: false,
              };
              return updated;
            }
            return prev;
          });
          break;
        }

        case "llm_token": {
          // Create or update the streaming assistant message
          setMessages((prev) => {
            const lastMsg = prev[prev.length - 1];
            if (lastMsg?.role === "assistant" && lastMsg.isStreaming) {
              // Update existing streaming message
              const updated = [...prev];
              updated[updated.length - 1] = {
                ...lastMsg,
                text: msg.accumulated,
                isThinkingPhase: false,
              };
              return updated;
            } else {
              // Create new assistant message
              const id =
                Date.now().toString(36) +
                Math.random().toString(36).slice(2, 7);
              streamingMsgIdRef.current = id;
              return [
                ...prev,
                {
                  id,
                  role: "assistant",
                  text: msg.accumulated,
                  isStreaming: true,
                  timestamp: new Date(),
                },
              ];
            }
          });
          break;
        }

        case "llm_complete": {
          setIsAssistantThinking(false);
          const targetId = streamingMsgIdRef.current;
          streamingMsgIdRef.current = null;
          // Finalize the bubble that llm_token / agent_action already created.
          // Never create a new bubble here — that would duplicate the response
          // (the streaming bubble already shows msg.text from the last token).
          if (!targetId) break;
          setMessages((prev) => {
            const idx = prev.findIndex((m) => m.id === targetId);
            if (idx < 0) return prev;
            const updated = [...prev];
            updated[idx] = {
              ...updated[idx],
              text: msg.text,
              isStreaming: false,
              isThinkingPhase: false,
            };
            return updated;
          });
          break;
        }

        case "tts_start": {
          // Initialize TTS player for this stream
          if (!ttsPlayerRef.current) {
            ttsPlayerRef.current = new TTSPlayer();
          }
          ttsPlayerRef.current.onPlaybackEnd = () => {
            setIsAssistantSpeaking(false);
          };
          ttsPlayerRef.current.start(msg.sample_rate);
          setIsAssistantSpeaking(true);
          break;
        }

        case "tts_end": {
          if (ttsPlayerRef.current) {
            ttsPlayerRef.current.end();
          }
          break;
        }

        case "error": {
          console.error("[Chat] Server error:", msg.message);
          setIsAssistantThinking(false);
          break;
        }

        case "status": {
          console.log("[Chat] Status:", msg.message);
          break;
        }

        case "notification": {
          // Proactive notification from scheduler (reminder, scheduled task)
          const notifId =
            Date.now().toString(36) +
            Math.random().toString(36).slice(2, 7);
          setMessages((prev) => [
            ...prev,
            {
              id: notifId,
              role: "assistant",
              text: msg.message,
              isStreaming: false,
              isNotification: true,
              taskId: msg.task_id,
              timestamp: new Date(),
            },
          ]);
          break;
        }
      }
    };

    // Handle binary messages (TTS audio chunks)
    const handleBinaryMessage = (data: ArrayBuffer) => {
      if (ttsPlayerRef.current) {
        ttsPlayerRef.current.enqueueChunk(data);
      }
    };

    ws.on("statusChange", handleStatusChange);
    ws.on("open", handleOpen);
    ws.on("message", handleMessage);
    ws.on("binaryMessage", handleBinaryMessage);

    ws.connect();

    return () => {
      ws.off("statusChange", handleStatusChange);
      ws.off("open", handleOpen);
      ws.off("message", handleMessage);
      ws.off("binaryMessage", handleBinaryMessage);
      // Do not disconnect the singleton — it's shared with useTerminal
      wsRef.current = null;
    };
  }, []);

  // Send config updates
  useEffect(() => {
    if (wsRef.current && wsStatus === "OPEN") {
      wsRef.current.sendConfig({
        language,
        thinking: thinkingEnabled,
      });
    }
  }, [language, thinkingEnabled, wsStatus]);

  // ── Controls ──

  const startRecording = useCallback(
    async (deviceId?: string) => {
      if (!vadRef.current || !vadRef.current.isReady) return;
      if (!navigator.mediaDevices?.getUserMedia) {
        console.error("Microphone not available (requires HTTPS or localhost)");
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

        const processor = audioContext.createScriptProcessor(512, 1, 1);
        processorRef.current = processor;

        source.connect(processor);

        const dummyGain = audioContext.createGain();
        dummyGain.gain.value = 0;
        processor.connect(dummyGain);
        dummyGain.connect(audioContext.destination);

        processor.onaudioprocess = (e) => {
          if (!isRecordingRef.current) return;

          const inputBuffer = new Float32Array(
            e.inputBuffer.getChannelData(0),
          );

          let maxVal = 0;
          for (let i = 0; i < inputBuffer.length; i++) {
            const val = inputBuffer[i];
            if (val > maxVal) maxVal = val;
            else if (-val > maxVal) maxVal = -val;
          }
          volumeRef.current = maxVal;

          vadRef.current?.processAudio(inputBuffer);
        };

        isRecordingRef.current = true;
        setIsRecording(true);

        if (wsRef.current && wsStatus === "CLOSED") {
          wsRef.current.connect();
        }
      } catch (err) {
        console.error("Microphone access error:", err);
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
  }, []);

  const sendTextMessage = useCallback(
    (text: string, images?: ImageAttachment[]) => {
      const trimmed = text.trim();
      if (!trimmed && !(images && images.length > 0)) return;

      // Add user message + streaming assistant placeholder so the
      // "Thinking..." indicator shows immediately while we wait for the
      // first LLM token.
      const userId =
        Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
      const placeholderId =
        Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
      streamingMsgIdRef.current = placeholderId;
      setMessages((prev) => [
        ...prev,
        {
          id: userId,
          role: "user",
          text: trimmed,
          images,
          timestamp: new Date(),
        },
        {
          id: placeholderId,
          role: "assistant",
          text: "",
          isStreaming: true,
          timestamp: new Date(),
        },
      ]);
      setIsAssistantThinking(true);

      // Stop any ongoing TTS before sending new input
      if (ttsPlayerRef.current) {
        ttsPlayerRef.current.stop();
        ttsPlayerRef.current = null;
        setIsAssistantSpeaking(false);
      }

      // Send to backend
      if (wsRef.current) {
        wsRef.current.sendUserMessage(trimmed, "keyboard", images);
      }
    },
    [],
  );

  const cancelGeneration = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.sendCancel();
    }
    setIsAssistantThinking(false);
    // Finalize any in-flight streaming assistant bubble so it stops
    // showing "Thinking..." forever. Drop it if it has no content at all.
    setMessages((prev) => {
      const lastIdx = prev.length - 1;
      const last = prev[lastIdx];
      if (!last || last.role !== "assistant" || !last.isStreaming) return prev;
      const hasContent =
        (last.text && last.text.trim()) ||
        (last.thinkingText && last.thinkingText.trim()) ||
        (last.agentActions && last.agentActions.length > 0);
      if (!hasContent) return prev.slice(0, -1);
      const updated = [...prev];
      updated[lastIdx] = { ...last, isStreaming: false, isThinkingPhase: false };
      return updated;
    });
    streamingMsgIdRef.current = null;
    if (ttsPlayerRef.current) {
      ttsPlayerRef.current.stop();
      ttsPlayerRef.current = null;
    }
    setIsAssistantSpeaking(false);
  }, []);

  const clearMessages = useCallback(() => {
    setMessages([]);
    if (wsRef.current) {
      wsRef.current.sendClearMemory();
    }
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (isRecordingRef.current) {
        stopRecording();
      }
    };
  }, [stopRecording]);

  return {
    isVADLoaded,
    isRecording,
    isSpeaking,
    volumeRef,

    wsStatus,
    isConnected: wsStatus === "OPEN",

    messages,
    isAssistantThinking,
    isAssistantSpeaking,

    language,
    setLanguage,
    thinkingEnabled,
    setThinkingEnabled,

    startRecording,
    stopRecording,
    sendTextMessage,
    cancelGeneration,
    clearMessages,
  };
}
