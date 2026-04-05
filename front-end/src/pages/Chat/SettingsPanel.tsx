import React, { useEffect, useState, useRef } from "react";
import { Flex, Box, Text, Select, Separator, Badge } from "@radix-ui/themes";
import type { WebSocketStatus } from "../../services/chat-websocket.service";
import { STT_LANGUAGES } from "../../constants/stt.constant";

export interface SettingsPanelProps {
  isLoaded: boolean;
  isRecording: boolean;
  volumeRef: React.RefObject<number>;
  onDeviceChange?: (deviceId: string) => void;
  selectedDeviceId?: string;
  wsStatus: WebSocketStatus;
  isConnected: boolean;
  language: string;
  onLanguageChange?: (lang: string) => void;
  isAssistantThinking?: boolean;
}

function getWsStatusDisplay(status: WebSocketStatus) {
  switch (status) {
    case "OPEN":
      return { label: "CONNECTED", color: "cyan" as const };
    case "CONNECTING":
      return { label: "CONNECTING", color: "orange" as const };
    case "CLOSING":
      return { label: "CLOSING", color: "orange" as const };
    case "CLOSED":
      return { label: "DISCONNECTED", color: "gray" as const };
    case "ERROR":
      return { label: "ERROR", color: "red" as const };
    default:
      return { label: status, color: "gray" as const };
  }
}

export default function SettingsPanel({
  isLoaded,
  isRecording,
  volumeRef,
  onDeviceChange,
  selectedDeviceId,
  wsStatus,
  language,
  onLanguageChange,
  isAssistantThinking,
}: SettingsPanelProps) {
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [ramUsage, setRamUsage] = useState<number | null>(null);

  const requestRef = useRef<number>(0);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const historyRef = useRef<number[]>(new Array(50).fill(0));

  useEffect(() => {
    if (navigator.mediaDevices?.getUserMedia) {
      navigator.mediaDevices
        .getUserMedia({ audio: true })
        .then((stream) => {
          navigator.mediaDevices.enumerateDevices().then((d) => {
            setDevices(d.filter((device) => device.kind === "audioinput"));
          });
          stream.getTracks().forEach((track) => track.stop());
        })
        .catch((err) => {
          console.warn("Could not get devices", err);
        });
    }

    const ramInterval = setInterval(() => {
      const perf = performance as any;
      if (perf.memory && perf.memory.usedJSHeapSize) {
        setRamUsage(Math.round(perf.memory.usedJSHeapSize / (1024 * 1024)));
      }
    }, 2000);

    return () => clearInterval(ramInterval);
  }, []);

  // Waveform animation
  const drawWaveform = () => {
    if (canvasRef.current) {
      const ctx = canvasRef.current.getContext("2d");
      if (ctx) {
        const width = canvasRef.current.width;
        const height = canvasRef.current.height;

        historyRef.current.shift();
        historyRef.current.push(isRecording ? volumeRef.current : 0);

        ctx.clearRect(0, 0, width, height);

        const barWidth = width / historyRef.current.length;

        ctx.beginPath();
        for (let i = 0; i < historyRef.current.length; i++) {
          const val = historyRef.current[i] * height * 2.5;
          const h = Math.max(2, Math.min(height, val));
          const x = i * barWidth;
          const y = (height - h) / 2;
          ctx.rect(x + 1, y, barWidth - 2, h);
        }

        ctx.fillStyle = isRecording ? "var(--indigo-9)" : "var(--gray-7)";
        ctx.fill();
      }
    }
    requestRef.current = requestAnimationFrame(drawWaveform);
  };

  useEffect(() => {
    requestRef.current = requestAnimationFrame(drawWaveform);
    return () => cancelAnimationFrame(requestRef.current);
  }, [isRecording]);

  const wsDisplay = getWsStatusDisplay(wsStatus);

  return (
    <Flex
      direction="column"
      style={{
        width: "320px",
        backgroundColor: "var(--color-panel-solid)",
        color: "var(--gray-12)",
        borderLeft: "1px solid var(--gray-5)",
        height: "100%",
        overflowY: "auto",
      }}
    >
      <Box p="4">
        <Text
          size="1"
          color="gray"
          weight="bold"
          style={{ textTransform: "uppercase", letterSpacing: "1px" }}
        >
          Shore Assistant
        </Text>
        <Text size="2" color="gray" mt="2" style={{ display: "block" }}>
          Voice AI with LLM, Tools & Vision
        </Text>
      </Box>

      <Separator size="4" style={{ backgroundColor: "var(--gray-5)" }} />

      <Box p="4">
        <Text
          size="1"
          color="gray"
          weight="bold"
          style={{ textTransform: "uppercase", letterSpacing: "1px" }}
        >
          Settings
        </Text>

        {/* Language Selector */}
        <Flex justify="between" align="center" mt="3">
          <Text size="2" color="gray">
            Language
          </Text>
          <Select.Root
            value={language}
            onValueChange={onLanguageChange}
            size="1"
          >
            <Select.Trigger
              variant="soft"
              style={{
                backgroundColor: "var(--gray-3)",
                color: "var(--gray-12)",
                border: "none",
                maxWidth: "120px",
              }}
            />
            <Select.Content
              position="popper"
              style={{
                backgroundColor: "var(--color-panel-solid)",
                color: "var(--gray-12)",
              }}
            >
              <Select.Group>
                {STT_LANGUAGES.map((lang) => (
                  <Select.Item key={lang.value} value={lang.value}>
                    {lang.label}
                  </Select.Item>
                ))}
              </Select.Group>
            </Select.Content>
          </Select.Root>
        </Flex>

        {/* LLM Model info */}
        <Flex justify="between" align="center" mt="2">
          <Text size="2" color="gray">
            LLM
          </Text>
          <Text size="2" style={{ color: "var(--indigo-9)" }}>
            Qwen2.5-14B
          </Text>
        </Flex>
      </Box>

      <Separator size="4" style={{ backgroundColor: "var(--gray-5)" }} />

      <Box p="4">
        <Text
          size="1"
          color="gray"
          weight="bold"
          style={{ textTransform: "uppercase", letterSpacing: "1px" }}
        >
          Status
        </Text>

        {/* VAD Model */}
        <Flex justify="between" mt="3">
          <Text size="2" color="gray">
            VAD Model
          </Text>
          {isLoaded ? (
            <Text
              size="2"
              style={{ color: "var(--cyan-10)", fontWeight: "500" }}
            >
              READY
            </Text>
          ) : (
            <Text size="2" color="orange">
              LOADING
            </Text>
          )}
        </Flex>

        {/* WebSocket / Backend */}
        <Flex justify="between" align="center" mt="2">
          <Text size="2" color="gray">
            Backend WS
          </Text>
          <Badge
            size="1"
            color={wsDisplay.color}
            variant="soft"
            style={{ fontWeight: "500", fontSize: "11px" }}
          >
            {wsDisplay.label}
          </Badge>
        </Flex>

        {/* Mic connected */}
        <Flex justify="between" mt="2">
          <Text size="2" color="gray">
            Mic connected
          </Text>
          <Text
            size="2"
            style={{
              color: isRecording ? "var(--cyan-10)" : "var(--gray-9)",
              fontWeight: "500",
            }}
          >
            {isRecording ? "TRUE" : "FALSE"}
          </Text>
        </Flex>

        {/* Agent status */}
        <Flex justify="between" mt="2">
          <Text size="2" color="gray">
            Agent
          </Text>
          <Text
            size="2"
            style={{
              color: isAssistantThinking
                ? "var(--orange-10)"
                : "var(--gray-9)",
              fontWeight: "500",
            }}
          >
            {isAssistantThinking ? "THINKING" : "IDLE"}
          </Text>
        </Flex>

        {/* RAM */}
        <Flex justify="between" mt="2">
          <Text size="2" color="gray">
            Web RAM Usage
          </Text>
          <Text
            size="2"
            style={{ color: "var(--orange-10)", fontWeight: "500" }}
          >
            {ramUsage ? `${ramUsage} MB` : "N/A"}
          </Text>
        </Flex>
      </Box>

      <Separator size="4" style={{ backgroundColor: "var(--gray-5)" }} />

      <Box p="4">
        <Flex justify="between" align="center" mb="3">
          <Text
            size="1"
            color="gray"
            weight="bold"
            style={{
              textTransform: "uppercase",
              letterSpacing: "1px",
              flexShrink: 0,
              marginRight: "8px",
            }}
          >
            Microphone
          </Text>
          <Select.Root
            value={selectedDeviceId || "default"}
            onValueChange={onDeviceChange}
            size="1"
          >
            <Select.Trigger
              variant="soft"
              style={{
                backgroundColor: "var(--gray-3)",
                color: "var(--gray-12)",
                border: "none",
                maxWidth: "160px",
              }}
            />
            <Select.Content
              position="popper"
              style={{
                backgroundColor: "var(--color-panel-solid)",
                color: "var(--gray-12)",
              }}
            >
              <Select.Group>
                <Select.Item value="default">Default Microphone</Select.Item>
                {devices.map((d) => (
                  <Select.Item key={d.deviceId} value={d.deviceId}>
                    {d.label || `Microphone ${d.deviceId.substring(0, 5)}`}
                  </Select.Item>
                ))}
              </Select.Group>
            </Select.Content>
          </Select.Root>
        </Flex>

        {/* Audio Visualizer */}
        <Box
          style={{
            height: "90px",
            backgroundColor: "var(--gray-2)",
            borderRadius: "6px",
            border: "1px solid var(--gray-5)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: "10px",
          }}
        >
          <canvas
            ref={canvasRef}
            width={260}
            height={60}
            style={{
              width: "100%",
              height: "100%",
              display: "block",
            }}
          />
        </Box>
      </Box>
    </Flex>
  );
}
