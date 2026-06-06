import { useCallback, useEffect, useState } from "react";
import {
  Box, Flex, Text, Button, Callout, TextField,
} from "@radix-ui/themes";
import { memoryApi, MemoryApiError } from "@Shore/services/memory-api.service";
import JsonTreeNode from "./components/JsonTreeNode";

interface Props {
  refreshTick: number;
  onMutate: () => void;
}

const PROFILE_MAX_BYTES = 2048;

export default function ProfileTab({ refreshTick, onMutate }: Props) {
  const [data, setData] = useState<Record<string, unknown>>({});
  const [sizeBytes, setSizeBytes] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [adding, setAdding] = useState(false);
  const [newKey, setNewKey] = useState("");
  const [newValue, setNewValue] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await memoryApi.getProfile();
      setData(res.data);
      setSizeBytes(res.size_bytes);
    } catch (e) {
      setError(e instanceof MemoryApiError ? e.detail : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load, refreshTick]);

  const handleChange = async (keyPath: string, value: unknown) => {
    try {
      await memoryApi.changeProfile(keyPath, value, "edited via memory panel");
      onMutate();
      await load();
    } catch (e) {
      setError(e instanceof MemoryApiError ? e.detail : String(e));
    }
  };

  const handleDelete = async (keyPath: string) => {
    try {
      await memoryApi.deleteProfileKey(keyPath, "deleted via memory panel");
      onMutate();
      await load();
    } catch (e) {
      setError(e instanceof MemoryApiError ? e.detail : String(e));
    }
  };

  const handleAddRoot = async () => {
    if (!newKey.trim()) return;
    let parsed: unknown = newValue;
    try {
      parsed = JSON.parse(newValue);
    } catch {
      // Treat as string if not valid JSON
    }
    await handleChange(newKey.trim(), parsed);
    setNewKey("");
    setNewValue("");
    setAdding(false);
  };

  const filtered = filter
    ? Object.fromEntries(
        Object.entries(data).filter(([k]) =>
          k.toLowerCase().includes(filter.toLowerCase()),
        ),
      )
    : data;

  const sizePct = Math.min(100, Math.round((sizeBytes / PROFILE_MAX_BYTES) * 100));
  const sizeColor =
    sizePct >= 90 ? "var(--red-9)"
    : sizePct >= 70 ? "var(--orange-9)"
    : "var(--cyan-9)";

  return (
    <Box p="5">
      {error && (
        <Callout.Root color="red" mb="3">
          <Callout.Text>Failed: {error}</Callout.Text>
        </Callout.Root>
      )}

      <Flex justify="between" align="center" mb="3" gap="3" wrap="wrap">
        <Flex align="center" gap="2" style={{ flex: 1, minWidth: 200 }}>
          <TextField.Root
            size="2"
            placeholder="Filter top-level keys…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            style={{ flex: 1, maxWidth: 320 }}
          />
        </Flex>
        <Flex align="center" gap="3">
          <Box style={{ minWidth: 140 }}>
            <Text size="1" color="gray">
              {sizeBytes} / {PROFILE_MAX_BYTES} B ({sizePct}%)
            </Text>
            <Box
              style={{
                marginTop: 2,
                height: 4,
                background: "var(--gray-4)",
                borderRadius: 2,
                overflow: "hidden",
              }}
            >
              <Box
                style={{
                  height: "100%",
                  width: `${sizePct}%`,
                  background: sizeColor,
                  transition: "width 200ms ease",
                }}
              />
            </Box>
          </Box>
          <Button
            size="1"
            variant="soft"
            color="cyan"
            onClick={() => setAdding((a) => !a)}
          >
            {adding ? "Cancel" : "+ Add root key"}
          </Button>
        </Flex>
      </Flex>

      {adding && (
        <Flex gap="2" align="center" mb="3" style={{ background: "var(--gray-2)", padding: 10, borderRadius: 6 }}>
          <TextField.Root
            size="1"
            placeholder="key name"
            value={newKey}
            onChange={(e) => setNewKey(e.target.value)}
            style={{ width: 160 }}
          />
          <TextField.Root
            size="1"
            placeholder='value (JSON or string, e.g. "Luna" or 42 or {"a":1})'
            value={newValue}
            onChange={(e) => setNewValue(e.target.value)}
            style={{ flex: 1 }}
          />
          <Button size="1" onClick={handleAddRoot} disabled={!newKey.trim()}>
            Add
          </Button>
        </Flex>
      )}

      {loading ? (
        <Text size="2" color="gray">Loading…</Text>
      ) : Object.keys(filtered).length === 0 ? (
        <Text size="2" color="gray" style={{ fontStyle: "italic" }}>
          {filter ? `No keys match "${filter}".` : "No profile data yet. Add a key to begin."}
        </Text>
      ) : (
        <Box
          style={{
            background: "var(--gray-2)",
            border: "1px solid var(--gray-5)",
            borderRadius: 6,
            padding: 8,
            fontFamily: "monospace",
            fontSize: 13,
          }}
        >
          {Object.entries(filtered).map(([k, v]) => (
            <JsonTreeNode
              key={k}
              keyName={k}
              keyPath={k}
              value={v}
              onChange={handleChange}
              onDelete={handleDelete}
            />
          ))}
        </Box>
      )}

      <Text size="1" color="gray" mt="3" style={{ display: "block" }}>
        Tip: nested edits use dot-notation key_path. Keys containing literal "." will conflict — avoid them.
      </Text>
    </Box>
  );
}
