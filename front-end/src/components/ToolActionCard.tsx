import { useState } from "react";
import { Flex, Box, Text } from "@radix-ui/themes";

export interface ToolActionCardProps {
  tool: string;
  args?: Record<string, unknown>;
  result?: string;
  status: "running" | "completed" | "error";
}

const RESULT_PREVIEW_LINES = 4;

const TOOL_DISPLAY_NAMES: Record<string, string> = {
  get_system_time: "System Time",
  read_file: "Read File",
  list_directory: "List Directory",
  clear_memory: "Clear Memory",
  search_web: "Web Search",
  web_scrape: "Web Scrape",
  capture_screen: "Screen Capture",
  analyze_screen: "Screen Analysis",
  set_reminder: "Set Reminder",
  set_scheduled_task: "Scheduled Task",
  cancel_task: "Cancel Task",
  list_tasks: "List Tasks",
};

function getToolDisplayName(tool: string): string {
  return TOOL_DISPLAY_NAMES[tool] || tool.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function StatusIcon({ status }: { status: ToolActionCardProps["status"] }) {
  if (status === "running") {
    return (
      <span
        style={{
          display: "inline-block",
          width: "14px",
          height: "14px",
          border: "2px solid var(--gray-6)",
          borderTopColor: "var(--indigo-9)",
          borderRadius: "50%",
          animation: "tool-spin 0.8s linear infinite",
        }}
      />
    );
  }
  if (status === "completed") {
    return (
      <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
        <circle cx="8" cy="8" r="7" stroke="var(--green-9)" strokeWidth="1.5" />
        <path d="M5 8l2 2 4-4" stroke="var(--green-9)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
      <circle cx="8" cy="8" r="7" stroke="var(--red-9)" strokeWidth="1.5" />
      <path d="M5.5 5.5l5 5M10.5 5.5l-5 5" stroke="var(--red-9)" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function FormatArgs({ args }: { args: Record<string, unknown> }) {
  const entries = Object.entries(args);
  if (entries.length === 0) return null;

  return (
    <Flex direction="column" gap="1" mt="1">
      {entries.map(([key, value]) => (
        <Flex key={key} gap="2" align="start">
          <Text size="1" style={{ color: "var(--gray-9)", flexShrink: 0 }}>
            {key}:
          </Text>
          <Text size="1" style={{ color: "var(--gray-11)", wordBreak: "break-word" }}>
            {typeof value === "string" ? value : JSON.stringify(value)}
          </Text>
        </Flex>
      ))}
    </Flex>
  );
}

export default function ToolActionCard({
  tool,
  args,
  result,
  status,
}: ToolActionCardProps) {
  const defaultExpanded = status === "error" || status === "running";
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);
  const [showFullResult, setShowFullResult] = useState(false);

  const hasResult = result !== undefined && result !== null;
  const isCollapsible = status !== "running";

  const resultLines = result?.split("\n") || [];
  const isResultLong = resultLines.length > RESULT_PREVIEW_LINES;
  const previewResult = isResultLong && !showFullResult
    ? resultLines.slice(0, RESULT_PREVIEW_LINES).join("\n") + "\n..."
    : result;

  const borderColor =
    status === "error"
      ? "var(--red-6)"
      : status === "running"
        ? "var(--indigo-6)"
        : "var(--gray-5)";

  return (
    <Box
      mb="2"
      style={{
        borderRadius: "8px",
        border: `1px solid ${borderColor}`,
        overflow: "hidden",
        fontSize: "12px",
      }}
    >
      <Flex
        align="center"
        gap="2"
        p="2"
        style={{
          backgroundColor: status === "error" ? "var(--red-2)" : "var(--gray-2)",
          cursor: isCollapsible ? "pointer" : "default",
          userSelect: "none",
        }}
        onClick={() => {
          if (isCollapsible) setIsExpanded(!isExpanded);
        }}
      >
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" style={{ flexShrink: 0 }}>
          <path
            d="M9.5 6.5l4-4M12 2l2 2M6.5 9.5l-4 4M4 12l2 2M10.5 10.5l-5-5M3.5 7.5L1 10l5 5 2.5-2.5M12.5 8.5L15 6l-5-5-2.5 2.5"
            stroke={status === "error" ? "var(--red-9)" : "var(--gray-10)"}
            strokeWidth="1.2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>

        <Text size="1" weight="medium" style={{ flex: 1, color: "var(--gray-12)" }}>
          {getToolDisplayName(tool)}
        </Text>

        <StatusIcon status={status} />

        {isCollapsible && (
          <Text size="1" style={{ color: "var(--gray-8)", fontSize: "10px" }}>
            {isExpanded ? "\u25B2" : "\u25BC"}
          </Text>
        )}
      </Flex>

      {(isExpanded || status === "running") && (
        <Box p="2" style={{ backgroundColor: "var(--gray-1)" }}>
          {args && Object.keys(args).length > 0 && (
            <FormatArgs args={args} />
          )}

          {hasResult && (
            <Box mt={args && Object.keys(args).length > 0 ? "2" : "0"}>
              <Box
                style={{
                  borderTop: "1px solid var(--gray-4)",
                  paddingTop: "6px",
                }}
              >
                <Text
                  size="1"
                  style={{
                    whiteSpace: "pre-wrap",
                    color: status === "error" ? "var(--red-11)" : "var(--gray-10)",
                    display: "block",
                    maxHeight: showFullResult ? "none" : "calc(1.4em * 4 + 4px)",
                    overflow: "hidden",
                  }}
                >
                  {previewResult}
                </Text>

                {isResultLong && (
                  <Text
                    size="1"
                    style={{
                      color: "var(--indigo-9)",
                      cursor: "pointer",
                      display: "inline-block",
                      marginTop: "4px",
                    }}
                    onClick={(e) => {
                      e.stopPropagation();
                      setShowFullResult(!showFullResult);
                    }}
                  >
                    {showFullResult ? "Show less" : "Show more"}
                  </Text>
                )}
              </Box>
            </Box>
          )}

          {status === "running" && !hasResult && (
            <Text size="1" style={{ color: "var(--gray-9)", fontStyle: "italic" }}>
              Running...
            </Text>
          )}
        </Box>
      )}

      <style>{`
        @keyframes tool-spin {
          to { transform: rotate(360deg); }
        }
      `}</style>
    </Box>
  );
}
