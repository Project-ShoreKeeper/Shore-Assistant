import { useState } from "react";
import { Flex, Box, Text, Button, TextField } from "@radix-ui/themes";

interface Props {
  keyName: string;
  keyPath: string;
  value: unknown;
  onChange: (keyPath: string, newValue: unknown) => void | Promise<void>;
  onDelete: (keyPath: string) => void | Promise<void>;
  depth?: number;
}

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function isArray(v: unknown): v is unknown[] {
  return Array.isArray(v);
}

function previewValue(v: unknown): string {
  if (typeof v === "string") return `"${v}"`;
  if (v === null) return "null";
  if (typeof v === "boolean" || typeof v === "number") return String(v);
  return JSON.stringify(v);
}

export default function JsonTreeNode({
  keyName, keyPath, value, onChange, onDelete, depth = 0,
}: Props) {
  const [open, setOpen] = useState(depth < 1);
  const [editing, setEditing] = useState(false);
  const [editVal, setEditVal] = useState("");
  const [confirmDel, setConfirmDel] = useState(false);
  const [adding, setAdding] = useState(false);
  const [newChildKey, setNewChildKey] = useState("");
  const [newChildVal, setNewChildVal] = useState("");

  const indent = depth * 14;

  // Reset confirm-delete after 3s
  const armDelete = () => {
    setConfirmDel(true);
    setTimeout(() => setConfirmDel(false), 3000);
  };

  const startEdit = () => {
    setEditVal(typeof value === "string" ? value : JSON.stringify(value));
    setEditing(true);
  };

  const saveEdit = () => {
    let parsed: unknown = editVal;
    if (typeof value !== "string") {
      try {
        parsed = JSON.parse(editVal);
      } catch {
        // Keep as string if user typed plain text
      }
    } else {
      parsed = editVal;
    }
    onChange(keyPath, parsed);
    setEditing(false);
  };

  const addChild = () => {
    if (!newChildKey.trim()) return;
    let parsed: unknown = newChildVal;
    try {
      parsed = JSON.parse(newChildVal);
    } catch {
      // string fallback
    }
    onChange(`${keyPath}.${newChildKey.trim()}`, parsed);
    setNewChildKey("");
    setNewChildVal("");
    setAdding(false);
  };

  // ── Container (object/array) ──────────────────────────────────────
  if (isObject(value) || isArray(value)) {
    const entries: [string, unknown][] = isArray(value)
      ? value.map((v, i) => [String(i), v])
      : Object.entries(value);
    const count = entries.length;
    const label = isArray(value) ? `[${count} item${count === 1 ? "" : "s"}]` : `{${count} key${count === 1 ? "" : "s"}}`;

    return (
      <Box style={{ paddingLeft: indent }}>
        <Flex align="center" gap="1" style={{ minHeight: 24 }}>
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            style={{
              all: "unset",
              cursor: "pointer",
              color: "var(--gray-11)",
              fontFamily: "monospace",
              fontSize: 11,
              width: 14,
              textAlign: "center",
            }}
            aria-label={open ? "Collapse" : "Expand"}
          >
            {open ? "▾" : "▸"}
          </button>
          <Text size="2" weight="medium" style={{ color: "var(--indigo-11)" }}>
            {keyName}
          </Text>
          <Text size="1" color="gray">{label}</Text>
          <Box style={{ flex: 1 }} />
          {!isArray(value) && (
            <Button size="1" variant="ghost" color="gray" onClick={() => setAdding((a) => !a)}>
              {adding ? "cancel" : "+ child"}
            </Button>
          )}
          <Button
            size="1"
            variant="ghost"
            color="red"
            onClick={() => (confirmDel ? onDelete(keyPath) : armDelete())}
          >
            {confirmDel ? "confirm?" : "delete"}
          </Button>
        </Flex>

        {open && adding && !isArray(value) && (
          <Flex gap="2" mt="1" mb="1" style={{ paddingLeft: indent + 14 }}>
            <TextField.Root
              size="1"
              placeholder="child key"
              value={newChildKey}
              onChange={(e) => setNewChildKey(e.target.value)}
              style={{ width: 140 }}
            />
            <TextField.Root
              size="1"
              placeholder="value (JSON or string)"
              value={newChildVal}
              onChange={(e) => setNewChildVal(e.target.value)}
              style={{ flex: 1 }}
            />
            <Button size="1" onClick={addChild} disabled={!newChildKey.trim()}>add</Button>
          </Flex>
        )}

        {open && entries.map(([childKey, childVal]) => (
          <JsonTreeNode
            key={childKey}
            keyName={childKey}
            keyPath={`${keyPath}.${childKey}`}
            value={childVal}
            onChange={onChange}
            onDelete={onDelete}
            depth={depth + 1}
          />
        ))}
      </Box>
    );
  }

  // ── Leaf ───────────────────────────────────────────────────────────
  const valueColor =
    typeof value === "string" ? "var(--green-11)"
    : typeof value === "number" ? "var(--cyan-11)"
    : typeof value === "boolean" ? "var(--orange-11)"
    : value === null ? "var(--gray-10)"
    : "var(--gray-12)";

  return (
    <Flex align="center" gap="2" style={{ paddingLeft: indent + 14, minHeight: 24 }}>
      <Text size="2" weight="medium" style={{ color: "var(--indigo-11)" }}>
        {keyName}:
      </Text>
      {editing ? (
        <>
          <TextField.Root
            size="1"
            value={editVal}
            onChange={(e) => setEditVal(e.target.value)}
            style={{ flex: 1, minWidth: 100, maxWidth: 400 }}
            autoFocus
            onKeyDown={(e) => {
              if (e.key === "Enter") saveEdit();
              if (e.key === "Escape") setEditing(false);
            }}
          />
          <Button size="1" onClick={saveEdit}>save</Button>
          <Button size="1" variant="ghost" color="gray" onClick={() => setEditing(false)}>cancel</Button>
        </>
      ) : (
        <>
          <Text
            size="2"
            style={{
              color: valueColor,
              fontFamily: "monospace",
              maxWidth: 480,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
            title={previewValue(value)}
          >
            {previewValue(value)}
          </Text>
          <Box style={{ flex: 1 }} />
          <Button size="1" variant="ghost" color="gray" onClick={startEdit}>edit</Button>
          <Button
            size="1"
            variant="ghost"
            color="red"
            onClick={() => (confirmDel ? onDelete(keyPath) : armDelete())}
          >
            {confirmDel ? "confirm?" : "delete"}
          </Button>
        </>
      )}
    </Flex>
  );
}
