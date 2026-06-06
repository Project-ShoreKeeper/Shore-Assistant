import { useCallback, useEffect, useState } from "react";
import {
  Box, Flex, Text, Button, Callout, Select, Badge, IconButton,
} from "@radix-ui/themes";
import {
  memoryApi, MemoryApiError, type AuditRow,
} from "@Shore/services/memory-api.service";
import AuditRowView from "./components/AuditRow";

interface Props {
  refreshTick: number;
  onRestore: () => void;
}

type Mode = { kind: "global" } | { kind: "key"; key: string };

export default function AuditTab({ refreshTick, onRestore }: Props) {
  const [mode, setMode] = useState<Mode>({ kind: "global" });
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [limit, setLimit] = useState(50);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      if (mode.kind === "global") {
        const res = await memoryApi.getAudit(limit);
        setRows(res.rows);
      } else {
        const res = await memoryApi.getProfileHistory(mode.key, limit);
        setRows(res.rows);
      }
    } catch (e) {
      setError(e instanceof MemoryApiError ? e.detail : String(e));
    } finally {
      setLoading(false);
    }
  }, [mode, limit]);

  useEffect(() => {
    load();
  }, [load, refreshTick]);

  const handleZoom = (key: string) => setMode({ kind: "key", key });
  const handleGlobal = () => setMode({ kind: "global" });

  const handleRestore = async (audit_id: number) => {
    setError(null);
    try {
      const res = await memoryApi.restore(audit_id);
      onRestore();
      // Prepend the new audit row at top
      setRows((rs) => [res.new_row, ...rs]);
    } catch (e) {
      setError(e instanceof MemoryApiError ? e.detail : String(e));
    }
  };

  return (
    <Box p="5">
      {error && (
        <Callout.Root color="red" mb="3">
          <Callout.Text>Failed: {error}</Callout.Text>
        </Callout.Root>
      )}

      <Flex gap="3" align="center" mb="3" wrap="wrap">
        <Text size="2" color="gray">scope:</Text>
        <Button
          size="1"
          variant={mode.kind === "global" ? "solid" : "soft"}
          color="indigo"
          onClick={handleGlobal}
        >
          Global
        </Button>
        {mode.kind === "key" && (
          <Badge size="2" color="cyan" variant="soft">
            key: <span style={{ fontFamily: "monospace" }}>{mode.key}</span>
            <IconButton
              size="1"
              variant="ghost"
              color="gray"
              onClick={handleGlobal}
              aria-label="Back to global"
              style={{ marginLeft: 4 }}
            >
              ✕
            </IconButton>
          </Badge>
        )}
        <Box style={{ flex: 1 }} />
        <Flex align="center" gap="2">
          <Text size="1" color="gray">limit</Text>
          <Select.Root
            size="1"
            value={String(limit)}
            onValueChange={(v) => setLimit(Number(v))}
          >
            <Select.Trigger />
            <Select.Content>
              <Select.Item value="25">25</Select.Item>
              <Select.Item value="50">50</Select.Item>
              <Select.Item value="100">100</Select.Item>
            </Select.Content>
          </Select.Root>
        </Flex>
      </Flex>

      {loading ? (
        <Text size="2" color="gray">Loading…</Text>
      ) : rows.length === 0 ? (
        <Text size="2" color="gray" style={{ fontStyle: "italic" }}>
          {mode.kind === "global"
            ? "No profile changes recorded yet."
            : `No history for "${mode.key}".`}
        </Text>
      ) : (
        <Flex direction="column" gap="2">
          {rows.map((r) => (
            <AuditRowView
              key={r.id}
              row={r}
              showKey={mode.kind === "global"}
              onZoomKey={handleZoom}
              onRestore={() => handleRestore(r.id)}
            />
          ))}
        </Flex>
      )}
    </Box>
  );
}
