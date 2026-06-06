import { useState } from "react";
import { Box, Flex, Text, Button } from "@radix-ui/themes";
import type { AuditRow } from "@Shore/services/memory-api.service";

interface Props {
  row: AuditRow;
  showKey: boolean;
  onZoomKey: (key: string) => void;
  onRestore: () => void;
}

function fmtTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function previewJson(v: unknown, max = 80): string {
  if (v === null || v === undefined) return "∅";
  const s = typeof v === "string" ? `"${v}"` : JSON.stringify(v);
  return s.length > max ? s.slice(0, max - 1) + "…" : s;
}

export default function AuditRowView({ row, showKey, onZoomKey, onRestore }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [confirmRestore, setConfirmRestore] = useState(false);

  const isDelete = row.new_value === null || row.new_value === undefined;
  const isCreate = row.old_value === null || row.old_value === undefined;
  const oldStr = previewJson(row.old_value);
  const newStr = previewJson(row.new_value);

  const arm = () => {
    setConfirmRestore(true);
    setTimeout(() => setConfirmRestore(false), 3000);
  };

  return (
    <Box
      style={{
        background: "var(--gray-2)",
        border: "1px solid var(--gray-5)",
        borderRadius: 8,
        padding: 10,
      }}
    >
      <Flex align="center" justify="between" gap="2" mb="1" wrap="wrap">
        <Flex align="center" gap="2">
          <Text size="1" color="gray" style={{ fontFamily: "monospace" }}>
            #{row.id}
          </Text>
          <Text size="1" color="gray">{fmtTime(row.created_at)}</Text>
          {showKey && (
            <Text
              size="2"
              weight="medium"
              style={{ color: "var(--indigo-11)", fontFamily: "monospace", cursor: "pointer" }}
              onClick={() => onZoomKey(row.key_path)}
              title="Click to zoom history for this key"
            >
              {row.key_path}
            </Text>
          )}
        </Flex>
        <Flex gap="1">
          {showKey && (
            <Button size="1" variant="ghost" color="gray" onClick={() => onZoomKey(row.key_path)}>
              zoom
            </Button>
          )}
          <Button
            size="1"
            variant="ghost"
            color="cyan"
            onClick={() => (confirmRestore ? onRestore() : arm())}
          >
            {confirmRestore ? "confirm restore?" : "↺ restore"}
          </Button>
        </Flex>
      </Flex>

      <Box
        style={{ fontFamily: "monospace", fontSize: 12, cursor: "pointer" }}
        onClick={() => setExpanded((e) => !e)}
        title="Click to expand full JSON"
      >
        {isCreate ? (
          <Text size="2" style={{ color: "var(--green-11)" }}>
            ∅ → <strong>{newStr}</strong>
          </Text>
        ) : isDelete ? (
          <Text size="2" style={{ color: "var(--red-11)" }}>
            <span style={{ textDecoration: "line-through" }}>{oldStr}</span> → ∅
          </Text>
        ) : (
          <Text size="2">
            <span style={{ color: "var(--gray-10)", textDecoration: "line-through" }}>{oldStr}</span>
            {"  →  "}
            <strong style={{ color: "var(--cyan-11)" }}>{newStr}</strong>
          </Text>
        )}
      </Box>

      {expanded && (
        <Box mt="2" style={{ fontFamily: "monospace", fontSize: 11, background: "var(--gray-3)", borderRadius: 4, padding: 8 }}>
          <Text size="1" color="gray" style={{ display: "block" }}>old:</Text>
          <pre style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-all" }}>
            {row.old_value === null || row.old_value === undefined
              ? "∅"
              : JSON.stringify(row.old_value, null, 2)}
          </pre>
          <Text size="1" color="gray" mt="2" style={{ display: "block" }}>new:</Text>
          <pre style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-all" }}>
            {row.new_value === null || row.new_value === undefined
              ? "∅"
              : JSON.stringify(row.new_value, null, 2)}
          </pre>
        </Box>
      )}

      <Text size="1" color="gray" mt="1" style={{ display: "block" }}>
        conf {row.confidence != null ? row.confidence.toFixed(2) : "—"} ·
        {row.source_turn_ts != null && row.source_turn_ts > 0
          ? ` src turn ${row.source_turn_ts.toFixed(0)} ·`
          : ""}
        {row.reason ? ` "${row.reason}"` : ""}
      </Text>
    </Box>
  );
}
