import { Flex, Box, Text } from "@radix-ui/themes";
import type { AgentAction } from "../hooks/useAssistant";

interface AgentActionLogProps {
  actions: AgentAction[];
  isThinking: boolean;
}

function getActionIcon(action: string): string {
  switch (action) {
    case "thinking":
      return "...";
    case "tool_call":
      return ">>>";
    case "tool_result":
      return "<<<";
    case "vision_swap":
      return "[V]";
    default:
      return "---";
  }
}

function getActionColor(action: string): string {
  switch (action) {
    case "thinking":
      return "var(--gray-10)";
    case "tool_call":
      return "var(--indigo-10)";
    case "tool_result":
      return "var(--cyan-10)";
    case "vision_swap":
      return "var(--orange-10)";
    default:
      return "var(--gray-10)";
  }
}

export default function AgentActionLog({
  actions,
  isThinking,
}: AgentActionLogProps) {
  if (actions.length === 0 && !isThinking) return null;

  return (
    <Box
      p="3"
      style={{
        backgroundColor: "var(--gray-2)",
        borderRadius: "8px",
        border: "1px solid var(--gray-4)",
        fontFamily: "monospace",
        fontSize: "12px",
        maxHeight: "200px",
        overflowY: "auto",
      }}
    >
      <Text
        size="1"
        weight="bold"
        color="gray"
        mb="2"
        style={{
          display: "block",
          textTransform: "uppercase",
          letterSpacing: "0.5px",
        }}
      >
        Agent Log
      </Text>

      {actions.map((a) => (
        <Flex key={a.id} gap="2" align="start" mb="1">
          <Text
            size="1"
            color="gray"
            style={{ flexShrink: 0, fontSize: "11px" }}
          >
            {a.timestamp.toLocaleTimeString([], {
              hour: "2-digit",
              minute: "2-digit",
              second: "2-digit",
            })}
          </Text>
          <Text
            size="1"
            style={{
              color: getActionColor(a.action),
              fontWeight: 600,
              flexShrink: 0,
              fontFamily: "monospace",
            }}
          >
            {getActionIcon(a.action)}
          </Text>
          <Text size="1" style={{ color: "var(--gray-11)", wordBreak: "break-word" }}>
            {a.detail}
            {a.tool && a.action === "tool_call" && a.args && (
              <span style={{ color: "var(--gray-8)" }}>
                {" "}
                {JSON.stringify(a.args)}
              </span>
            )}
            {a.result && (
              <span
                style={{
                  display: "block",
                  color: "var(--gray-9)",
                  marginTop: "2px",
                  whiteSpace: "pre-wrap",
                }}
              >
                {a.result.length > 200
                  ? a.result.substring(0, 200) + "..."
                  : a.result}
              </span>
            )}
          </Text>
        </Flex>
      ))}

      {isThinking && actions.length === 0 && (
        <Flex gap="2" align="center">
          <Text
            size="1"
            style={{
              color: "var(--indigo-9)",
              animation: "pulse 1.5s infinite",
            }}
          >
            Processing...
          </Text>
        </Flex>
      )}
    </Box>
  );
}
