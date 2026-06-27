import React, { useEffect, useState, useRef } from "react";
import {
  Flex,
  Box,
  Text,
  Select,
  Separator,
  Badge,
  Button,
  Switch,
  IconButton,
  Tooltip,
} from "@radix-ui/themes";
import type { WebSocketStatus } from "../../services/chat-websocket.service";
import type {
  MemoryWorkerStatus,
  MemoryWorkerLogEntry,
} from "../../hooks/useAssistant";
import { STT_LANGUAGES } from "../../constants/stt.constant";
import { BACKEND_URL } from "../../constants/backend.constant";

const EXPANDED_WIDTH = 320;
const COLLAPSED_WIDTH = 48;

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
  thinkingEnabled?: boolean;
  onThinkingEnabledChange?: (enabled: boolean) => void;
  copilotEnabled?: boolean;
  onCopilotEnabledChange?: (enabled: boolean) => void;
  onClearMessages?: () => void;
  messageCount?: number;
  collapsed: boolean;
  onToggleCollapsed: () => void;
  terminalOpen: boolean;
  onToggleTerminal: () => void;
  pendingConfirmsCount: number;
  sessionsCount: number;
  memoryWorkerStatus: MemoryWorkerStatus;
  memoryWorkerLog: MemoryWorkerLogEntry[];
}

// ── Icons (inline SVG to match codebase convention) ───────────────────

function ChevronLeft() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden>
      <path d="M10 12L6 8L10 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function ChevronRight() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden>
      <path d="M6 4L10 8L6 12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function ChevronDown() {
  return (
    <svg width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden>
      <path d="M4 6L8 10L12 6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function GearIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1.6" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
    </svg>
  );
}

function MicIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <rect x="9" y="3" width="6" height="11" rx="3" stroke="currentColor" strokeWidth="1.6" />
      <path d="M5 11C5 14.87 8.13 18 12 18C15.87 18 19 14.87 19 11" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <path d="M12 18V22" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M4 7H20" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <path d="M10 11V17M14 11V17" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <path d="M6 7L7 20C7 20.55 7.45 21 8 21H16C16.55 21 17 20.55 17 20L18 7" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M9 7V4C9 3.45 9.45 3 10 3H14C14.55 3 15 3.45 15 4V7" stroke="currentColor" strokeWidth="1.6" />
    </svg>
  );
}

function TerminalIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <rect x="2.5" y="3.5" width="19" height="16" rx="2" stroke="currentColor" strokeWidth="1.6" />
      <path d="M6 9l3 3-3 3M12 15h6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

// ── Status helpers ─────────────────────────────────────────────────────

type DotColor = "green" | "orange" | "red" | "gray";

const DOT_STYLE: Record<DotColor, string> = {
  green: "var(--cyan-10)",
  orange: "var(--orange-10)",
  red: "var(--red-10)",
  gray: "var(--gray-7)",
};

function wsDot(status: WebSocketStatus): DotColor {
  switch (status) {
    case "OPEN": return "green";
    case "CONNECTING":
    case "CLOSING": return "orange";
    case "ERROR": return "red";
    case "CLOSED":
    default: return "gray";
  }
}

function wsLabel(status: WebSocketStatus): string {
  switch (status) {
    case "OPEN": return "Connected";
    case "CONNECTING": return "Connecting…";
    case "CLOSING": return "Closing…";
    case "ERROR": return "Error";
    case "CLOSED":
    default: return "Disconnected";
  }
}

const SEVERITY: Record<DotColor, number> = { red: 3, orange: 2, green: 1, gray: 0 };
function worst(...colors: DotColor[]): DotColor {
  return colors.reduce((a, b) => (SEVERITY[a] >= SEVERITY[b] ? a : b), "gray");
}

function Dot({ color, size = 8 }: { color: DotColor; size?: number }) {
  return (
    <span
      style={{
        display: "inline-block",
        width: size,
        height: size,
        borderRadius: "50%",
        backgroundColor: DOT_STYLE[color],
        flexShrink: 0,
      }}
    />
  );
}

// ── Component ──────────────────────────────────────────────────────────

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
  thinkingEnabled = false,
  onThinkingEnabledChange,
  copilotEnabled = false,
  onCopilotEnabledChange,
  onClearMessages,
  messageCount = 0,
  collapsed,
  onToggleCollapsed,
  terminalOpen,
  onToggleTerminal,
  pendingConfirmsCount,
  sessionsCount,
  memoryWorkerStatus,
  memoryWorkerLog,
}: SettingsPanelProps) {
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [ramUsage, setRamUsage] = useState<number | null>(null);
  const [llmModel, setLlmModel] = useState<string>("—");
  const [toolsOpen, setToolsOpen] = useState(false);

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

    fetch(`${BACKEND_URL}/config`)
      .then((r) => r.json())
      .then((data) => setLlmModel(data.llm_model || "—"))
      .catch(() => setLlmModel("—"));

    const ramInterval = setInterval(() => {
      const perf = performance as unknown as { memory?: { usedJSHeapSize: number } };
      if (perf.memory?.usedJSHeapSize) {
        setRamUsage(Math.round(perf.memory.usedJSHeapSize / (1024 * 1024)));
      }
    }, 2000);

    return () => clearInterval(ramInterval);
  }, []);

  // Waveform animation — only when expanded (canvas isn't mounted while collapsed).
  useEffect(() => {
    if (collapsed) return;
    const draw = () => {
      const canvas = canvasRef.current;
      if (canvas) {
        const ctx = canvas.getContext("2d");
        if (ctx) {
          const width = canvas.width;
          const height = canvas.height;

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
      requestRef.current = requestAnimationFrame(draw);
    };
    requestRef.current = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(requestRef.current);
  }, [isRecording, collapsed, volumeRef]);

  // Derived status
  const vadColor: DotColor = isLoaded ? "green" : "orange";
  const wsColor = wsDot(wsStatus);
  const micColor: DotColor = isRecording ? "green" : "gray";
  const agentColor: DotColor = isAssistantThinking ? "orange" : "gray";
  const overallColor = worst(vadColor, wsColor); // agent thinking / mic idle aren't "issues"

  const handleClear = () => {
    if (messageCount === 0) return;
    if (window.confirm(`Clear ${messageCount} message${messageCount === 1 ? "" : "s"} and reset memory?`)) {
      onClearMessages?.();
    }
  };

  // ── Collapsed render ─────────────────────────────────────────────────
  if (collapsed) {
    const statusTooltip = `VAD ${isLoaded ? "ready" : "loading"} · WS ${wsLabel(wsStatus)} · Mic ${isRecording ? "on" : "off"} · Agent ${isAssistantThinking ? "thinking" : "idle"}`;
    return (
      <Flex
        direction="column"
        align="center"
        py="2"
        gap="3"
        style={{
          width: COLLAPSED_WIDTH,
          backgroundColor: "var(--color-panel-solid)",
          borderLeft: "1px solid var(--gray-5)",
          height: "100%",
          flexShrink: 0,
          transition: "width 200ms ease",
        }}
      >
        <Tooltip content="Expand settings">
          <IconButton size="1" variant="ghost" color="gray" onClick={onToggleCollapsed} aria-label="Expand settings">
            <ChevronLeft />
          </IconButton>
        </Tooltip>
        <Tooltip content="Settings">
          <IconButton size="2" variant="ghost" color="gray" onClick={onToggleCollapsed} aria-label="Settings">
            <GearIcon />
          </IconButton>
        </Tooltip>
        <Tooltip content={statusTooltip}>
          <Box style={{ padding: 6, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <Dot color={overallColor} size={12} />
          </Box>
        </Tooltip>
        <Tooltip content={`Microphone — ${isRecording ? "recording" : "idle"}`}>
          <Box style={{ position: "relative", padding: 6 }}>
            <MicIcon />
            <span
              style={{
                position: "absolute",
                bottom: 4,
                right: 2,
                width: 8,
                height: 8,
                borderRadius: "50%",
                backgroundColor: DOT_STYLE[micColor],
                border: "1.5px solid var(--color-panel-solid)",
              }}
            />
          </Box>
        </Tooltip>
        <Tooltip content={
          pendingConfirmsCount > 0
            ? `Terminal — ${pendingConfirmsCount} pending confirm${pendingConfirmsCount === 1 ? "" : "s"}`
            : sessionsCount > 0
              ? `Terminal — ${sessionsCount} session${sessionsCount === 1 ? "" : "s"} (${terminalOpen ? "open" : "closed"})`
              : `Terminal (${terminalOpen ? "open" : "closed"})`
        }>
          <IconButton
            size="2"
            variant={terminalOpen ? "solid" : "ghost"}
            color={pendingConfirmsCount > 0 ? "amber" : terminalOpen ? "indigo" : "gray"}
            onClick={onToggleTerminal}
            aria-label="Toggle terminal"
            style={{ position: "relative" }}
          >
            <TerminalIcon />
            {(pendingConfirmsCount > 0 || sessionsCount > 0) && (
              <span
                style={{
                  position: "absolute",
                  top: 2,
                  right: 2,
                  minWidth: 14,
                  height: 14,
                  padding: "0 3px",
                  borderRadius: 7,
                  fontSize: 9,
                  fontWeight: 700,
                  lineHeight: "14px",
                  color: "white",
                  backgroundColor: pendingConfirmsCount > 0 ? "var(--red-9)" : "var(--gray-9)",
                  border: "1.5px solid var(--color-panel-solid)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                {pendingConfirmsCount > 0 ? pendingConfirmsCount : sessionsCount}
              </span>
            )}
          </IconButton>
        </Tooltip>
        <Tooltip content="Clear chat & memory">
          <IconButton size="2" variant="ghost" color="red" onClick={handleClear} disabled={messageCount === 0} aria-label="Clear chat and memory">
            <TrashIcon />
          </IconButton>
        </Tooltip>
      </Flex>
    );
  }

  // ── Expanded render ──────────────────────────────────────────────────
  return (
    <Flex
      direction="column"
      style={{
        width: EXPANDED_WIDTH,
        backgroundColor: "var(--color-panel-solid)",
        color: "var(--gray-12)",
        borderLeft: "1px solid var(--gray-5)",
        height: "100%",
        overflowY: "auto",
        flexShrink: 0,
        transition: "width 200ms ease",
      }}
    >
      {/* Header — chevron only, no brand (left sidebar has it) */}
      <Flex align="center" justify="end" px="3" pt="2">
        <Tooltip content="Collapse sidebar">
          <IconButton size="1" variant="ghost" color="gray" onClick={onToggleCollapsed} aria-label="Collapse sidebar">
            <ChevronRight />
          </IconButton>
        </Tooltip>
      </Flex>

      {/* SETTINGS */}
      <Box px="4" pt="2">
        <Text size="1" color="gray" weight="bold" style={{ textTransform: "uppercase", letterSpacing: "1px" }}>
          Settings
        </Text>

        <Flex justify="between" align="center" mt="3">
          <Text size="2" color="gray">Language</Text>
          <Select.Root value={language} onValueChange={onLanguageChange} size="1">
            <Select.Trigger
              variant="soft"
              style={{ backgroundColor: "var(--gray-3)", color: "var(--gray-12)", border: "none", maxWidth: "120px" }}
            />
            <Select.Content position="popper" style={{ backgroundColor: "var(--color-panel-solid)", color: "var(--gray-12)" }}>
              <Select.Group>
                {STT_LANGUAGES.map((lang) => (
                  <Select.Item key={lang.value} value={lang.value}>{lang.label}</Select.Item>
                ))}
              </Select.Group>
            </Select.Content>
          </Select.Root>
        </Flex>

        <Flex justify="between" align="center" mt="2">
          <Text size="2" color="gray">LLM</Text>
          <Text size="2" style={{ color: "var(--indigo-9)", maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={llmModel}>
            {llmModel}
          </Text>
        </Flex>

        <Flex justify="between" align="center" mt="2">
          <Text size="2" color="gray">Thinking</Text>
          <Switch size="1" checked={thinkingEnabled} onCheckedChange={onThinkingEnabledChange} />
        </Flex>
        <Flex justify="between" align="center" mt="2">
          <Text size="2" color="gray">Co-pilot</Text>
          <Switch size="1" checked={copilotEnabled} onCheckedChange={onCopilotEnabledChange} />
        </Flex>
      </Box>

      <Separator size="4" my="3" style={{ backgroundColor: "var(--gray-5)" }} />

      {/* STATUS — single dot row */}
      <Box px="4">
        <Flex justify="between" align="center">
          <Text size="1" color="gray" weight="bold" style={{ textTransform: "uppercase", letterSpacing: "1px" }}>
            Status
          </Text>
          <Text size="1" color="orange">{ramUsage != null ? `${ramUsage} MB` : "—"}</Text>
        </Flex>
        <Flex gap="3" align="center" mt="2">
          <Tooltip content={`VAD — ${isLoaded ? "ready" : "loading"}`}>
            <Flex direction="column" align="center" gap="1" style={{ cursor: "default" }}>
              <Dot color={vadColor} />
              <Text size="1" color="gray">V</Text>
            </Flex>
          </Tooltip>
          <Tooltip content={`WebSocket — ${wsLabel(wsStatus)}`}>
            <Flex direction="column" align="center" gap="1" style={{ cursor: "default" }}>
              <Dot color={wsColor} />
              <Text size="1" color="gray">W</Text>
            </Flex>
          </Tooltip>
          <Tooltip content={`Microphone — ${isRecording ? "recording" : "idle"}`}>
            <Flex direction="column" align="center" gap="1" style={{ cursor: "default" }}>
              <Dot color={micColor} />
              <Text size="1" color="gray">M</Text>
            </Flex>
          </Tooltip>
          <Tooltip content={`Agent — ${isAssistantThinking ? "thinking" : "idle"}`}>
            <Flex direction="column" align="center" gap="1" style={{ cursor: "default" }}>
              <Dot color={agentColor} />
              <Text size="1" color="gray">A</Text>
            </Flex>
          </Tooltip>
          <Box style={{ flex: 1 }} />
          <Badge size="1" color={wsColor === "green" ? "cyan" : wsColor === "red" ? "red" : "orange"} variant="soft" style={{ fontSize: 10 }}>
            {wsLabel(wsStatus)}
          </Badge>
        </Flex>
      </Box>

      <Separator size="4" my="3" style={{ backgroundColor: "var(--gray-5)" }} />

      {/* MICROPHONE */}
      <Box px="4">
        <Flex justify="between" align="center">
          <Text size="1" color="gray" weight="bold" style={{ textTransform: "uppercase", letterSpacing: "1px", flexShrink: 0, marginRight: 8 }}>
            Microphone
          </Text>
          <Select.Root value={selectedDeviceId || "default"} onValueChange={onDeviceChange} size="1">
            <Select.Trigger
              variant="soft"
              style={{ backgroundColor: "var(--gray-3)", color: "var(--gray-12)", border: "none", maxWidth: 160 }}
            />
            <Select.Content position="popper" style={{ backgroundColor: "var(--color-panel-solid)", color: "var(--gray-12)" }}>
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
        <Box
          mt="2"
          style={{
            height: 70,
            backgroundColor: "var(--gray-2)",
            borderRadius: 6,
            border: "1px solid var(--gray-5)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 8,
          }}
        >
          <canvas
            ref={canvasRef}
            width={260}
            height={50}
            style={{ width: "100%", height: "100%", display: "block" }}
          />
        </Box>
      </Box>

      <Separator size="4" my="3" style={{ backgroundColor: "var(--gray-5)" }} />

      {/* ACTIONS */}
      <Box px="4">
        <Flex direction="column" gap="2">
          <Button
            size="1"
            color="cyan"
            variant="soft"
            style={{ cursor: "pointer" }}
            onClick={async () => {
              try {
                const res = await fetch(`${BACKEND_URL}/api/n8n/refresh`, { method: "POST" });
                const data = await res.json();
                alert(`Refreshed: ${data.workflows_discovered} workflow(s) found`);
              } catch {
                alert("Failed to refresh n8n workflows");
              }
            }}
          >
            Refresh n8n workflows
          </Button>
          <Button
            size="1"
            color={pendingConfirmsCount > 0 ? "amber" : terminalOpen ? "indigo" : "gray"}
            variant={terminalOpen ? "solid" : "soft"}
            style={{ cursor: "pointer", position: "relative" }}
            onClick={onToggleTerminal}
          >
            <Flex align="center" gap="1">
              <TerminalIcon />
              <span>Terminal{terminalOpen ? "  ▾" : ""}</span>
            </Flex>
            {(pendingConfirmsCount > 0 || sessionsCount > 0) && (
              <Badge
                size="1"
                color={pendingConfirmsCount > 0 ? "red" : "gray"}
                variant="solid"
                style={{ marginLeft: "auto", fontSize: 10, padding: "0 6px" }}
              >
                {pendingConfirmsCount > 0
                  ? `${pendingConfirmsCount} pending`
                  : `${sessionsCount} session${sessionsCount === 1 ? "" : "s"}`}
              </Badge>
            )}
          </Button>
          <Button
            size="1"
            color="red"
            variant="soft"
            style={{ cursor: "pointer" }}
            onClick={handleClear}
            disabled={messageCount === 0}
          >
            Clear chat &amp; memory
          </Button>
        </Flex>
      </Box>

      <Separator size="4" my="3" style={{ backgroundColor: "var(--gray-5)" }} />

      {/* AVAILABLE TOOLS — accordion, closed by default */}
      <Box px="4">
        <button
          type="button"
          aria-expanded={toolsOpen}
          onClick={() => setToolsOpen((o) => !o)}
          style={{
            all: "unset",
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            width: "100%",
          }}
        >
          <Text size="1" color="gray" weight="bold" style={{ textTransform: "uppercase", letterSpacing: "1px" }}>
            Available Tools
          </Text>
          <Box
            style={{
              color: "var(--gray-10)",
              transform: toolsOpen ? "rotate(0deg)" : "rotate(-90deg)",
              transition: "transform 150ms ease",
              display: "flex",
            }}
          >
            <ChevronDown />
          </Box>
        </button>

        {toolsOpen && (
          <Flex direction="column" gap="3" mt="3">
            <ToolGroup
              title="System"
              items={[
                '"What time is it?" — get current date/time',
                '"Read file X" / "List files in Y" — local file access',
                '"Forget everything" — clear conversation memory',
              ]}
            />
            <ToolGroup
              title="Web"
              items={[
                '"Search for ..." — web search via DuckDuckGo',
                '"Read this page: url" — scrape a web page',
              ]}
            />
            <ToolGroup
              title="Vision"
              items={['"What\'s on my screen?" — capture and analyze screen']}
            />
            <ToolGroup
              title="Reminders & Scheduling"
              items={[
                '"Remind me in 10 min to ..." — one-time reminder',
                '"Every 30 min, remind me to ..." — recurring task',
                '"List my tasks" — show active reminders',
                '"Cancel task rem_XXXX" — cancel by ID',
              ]}
            />
          </Flex>
        )}
      </Box>

      <Separator size="4" my="3" style={{ backgroundColor: "var(--gray-5)" }} />

      {/* MEMORY — LOCOMO worker status + log */}
      <Box px="4" pb="4">
        <Flex justify="between" align="center">
          <Flex align="center" gap="2">
            <MemoryDot status={memoryWorkerStatus} />
            <Text size="1" color="gray" weight="bold" style={{ textTransform: "uppercase", letterSpacing: "1px" }}>
              Memory
            </Text>
          </Flex>
          <Text size="1" color="gray">
            {memoryWorkerLabel(memoryWorkerStatus)}
          </Text>
        </Flex>
        <Box
          mt="2"
          style={{
            maxHeight: 140,
            overflowY: "auto",
            overscrollBehavior: "contain",
            backgroundColor: "var(--gray-2)",
            border: "1px solid var(--gray-5)",
            borderRadius: 6,
            padding: "6px 8px",
            fontFamily: "monospace",
            fontSize: 11,
            lineHeight: 1.5,
          }}
        >
          {memoryWorkerLog.length === 0 ? (
            <Text size="1" color="gray" style={{ fontStyle: "italic" }}>
              No extraction events yet.
            </Text>
          ) : (
            memoryWorkerLog
              .slice()
              .reverse()
              .map((entry) => (
                <Box key={entry.id} style={{ color: memoryLogColor(entry.stage) }}>
                  <span style={{ color: "var(--gray-9)" }}>
                    {entry.timestamp.toLocaleTimeString([], {
                      hour: "2-digit",
                      minute: "2-digit",
                      second: "2-digit",
                    })}
                  </span>{" "}
                  {memoryLogPrefix(entry.stage)} {entry.message}
                </Box>
              ))
          )}
        </Box>
      </Box>
    </Flex>
  );
}

function MemoryDot({ status }: { status: MemoryWorkerStatus }) {
  const color: DotColor =
    status === "extracting" ? "orange"
    : status === "error" ? "red"
    : status === "ok" ? "green"
    : "gray";
  return (
    <span
      style={{
        display: "inline-block",
        width: 8,
        height: 8,
        borderRadius: "50%",
        backgroundColor: DOT_STYLE[color],
        flexShrink: 0,
        animation: status === "extracting" ? "pulse 1s infinite" : undefined,
      }}
    />
  );
}

function memoryWorkerLabel(status: MemoryWorkerStatus): string {
  switch (status) {
    case "extracting": return "Updating…";
    case "ok": return "Up to date";
    case "error": return "Error";
    case "idle":
    default: return "Idle";
  }
}

function memoryLogPrefix(stage: MemoryWorkerLogEntry["stage"]): string {
  switch (stage) {
    case "started": return "•";
    case "completed": return "✓";
    case "failed": return "✗";
  }
}

function memoryLogColor(stage: MemoryWorkerLogEntry["stage"]): string {
  switch (stage) {
    case "started": return "var(--orange-11)";
    case "completed": return "var(--cyan-11)";
    case "failed": return "var(--red-11)";
  }
}

function ToolGroup({ title, items }: { title: string; items: string[] }) {
  return (
    <Box>
      <Text size="2" weight="medium" style={{ color: "var(--indigo-9)" }}>
        {title}
      </Text>
      {items.map((line, i) => (
        <Text key={i} size="1" color="gray" style={{ display: "block", marginTop: i === 0 ? 2 : 0 }}>
          {line}
        </Text>
      ))}
    </Box>
  );
}
