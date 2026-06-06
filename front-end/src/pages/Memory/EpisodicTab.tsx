import { useCallback, useEffect, useRef, useState } from "react";
import {
  Box, Flex, Text, Button, Callout, TextField, TextArea, Select, Slider, Badge,
} from "@radix-ui/themes";
import {
  memoryApi, MemoryApiError, type EpisodicRow,
} from "@Shore/services/memory-api.service";
import EpisodicCard from "./components/EpisodicCard";

interface Props {
  refreshTick: number;
}

type Mode = "recent" | "search";

export default function EpisodicTab({ refreshTick }: Props) {
  const [mode, setMode] = useState<Mode>("recent");
  const [rows, setRows] = useState<EpisodicRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [limit, setLimit] = useState(50);
  const [search, setSearch] = useState("");
  const [adding, setAdding] = useState(false);

  // Upsert form state
  const [factText, setFactText] = useState("");
  const [tagsText, setTagsText] = useState("");
  const [valence, setValence] = useState(0);
  const [confidence, setConfidence] = useState(1);
  const [sourceRole, setSourceRole] = useState<"user" | "assistant" | "manual">("manual");
  const [saving, setSaving] = useState(false);

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const loadRecent = useCallback(async (lim = limit) => {
    setLoading(true);
    setError(null);
    try {
      const res = await memoryApi.getEpisodicRecent(lim);
      setRows(res.rows);
      setMode("recent");
    } catch (e) {
      setError(e instanceof MemoryApiError ? e.detail : String(e));
    } finally {
      setLoading(false);
    }
  }, [limit]);

  const runSearch = useCallback(async (q: string) => {
    setLoading(true);
    setError(null);
    try {
      const res = await memoryApi.searchEpisodic(q, 20);
      setRows(res.hits);
      setMode("search");
    } catch (e) {
      setError(e instanceof MemoryApiError ? e.detail : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadRecent();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshTick]);

  // Debounced search
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    const q = search.trim();
    if (q.length === 0) {
      if (mode === "search") loadRecent();
      return;
    }
    if (q.length < 3) return;
    debounceRef.current = setTimeout(() => runSearch(q), 300);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const handleDelete = async (point_id: string) => {
    const prev = rows;
    setRows((rs) => rs.filter((r) => r.point_id !== point_id));
    try {
      await memoryApi.deleteEpisodic(point_id);
    } catch (e) {
      setRows(prev);
      setError(e instanceof MemoryApiError ? e.detail : String(e));
    }
  };

  const valenceToEmotion = (v: number): Record<string, number> => {
    if (v >= 0) return { joy: v, trust: v / 2 };
    return { sadness: -v, fear: -v / 2 };
  };

  const handleUpsert = async () => {
    if (!factText.trim()) return;
    setSaving(true);
    try {
      const tags = tagsText
        .split(",").map((t) => t.trim()).filter(Boolean);
      const res = await memoryApi.upsertEpisodic({
        fact: factText.trim(),
        entity_tags: tags,
        emotion: valenceToEmotion(valence),
        confidence,
        source_role: sourceRole,
        source_turn_ts: Date.now() / 1000,
      });
      // Prepend the new card optimistically (we know point_id from response)
      const newRow: EpisodicRow = {
        point_id: res.point_id,
        score: 1.0,
        created_at: Date.now() / 1000,
        fact: factText.trim(),
        entity_tags: tags,
        emotion: valenceToEmotion(valence) as Record<string, number>,
        valence,
        source_turn_ts: Date.now() / 1000,
        source_role: sourceRole,
        confidence,
      };
      setRows((rs) => [newRow, ...rs]);
      setFactText("");
      setTagsText("");
      setValence(0);
      setConfidence(1);
      setSourceRole("manual");
      setAdding(false);
    } catch (e) {
      setError(e instanceof MemoryApiError ? e.detail : String(e));
    } finally {
      setSaving(false);
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
        <TextField.Root
          size="2"
          placeholder="Search facts semantically (≥3 chars)…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ flex: 1, minWidth: 240 }}
        />
        {search && (
          <Button size="1" variant="soft" color="gray" onClick={() => setSearch("")}>
            Clear
          </Button>
        )}
        <Button
          size="1"
          variant="soft"
          color="cyan"
          onClick={() => setAdding((a) => !a)}
        >
          {adding ? "Cancel" : "+ New fact"}
        </Button>
      </Flex>

      <Flex gap="3" align="center" mb="3">
        <Text size="1" color="gray">
          {rows.length} fact{rows.length === 1 ? "" : "s"}
        </Text>
        {mode === "search" && (
          <Badge size="1" color="indigo" variant="soft">
            search: "{search}"
          </Badge>
        )}
        {mode === "recent" && (
          <Flex align="center" gap="2">
            <Text size="1" color="gray">limit</Text>
            <Select.Root
              size="1"
              value={String(limit)}
              onValueChange={(v) => {
                const n = Number(v);
                setLimit(n);
                loadRecent(n);
              }}
            >
              <Select.Trigger />
              <Select.Content>
                <Select.Item value="25">25</Select.Item>
                <Select.Item value="50">50</Select.Item>
                <Select.Item value="100">100</Select.Item>
              </Select.Content>
            </Select.Root>
          </Flex>
        )}
      </Flex>

      {adding && (
        <Box mb="4" style={{ background: "var(--gray-2)", padding: 12, borderRadius: 8, border: "1px solid var(--gray-5)" }}>
          <Text size="2" weight="medium" mb="2" style={{ display: "block" }}>New episodic fact</Text>
          <TextArea
            placeholder="The fact (e.g., 'Luna prefers oolong tea over green')"
            value={factText}
            onChange={(e) => setFactText(e.target.value)}
            size="2"
            style={{ marginBottom: 8 }}
          />
          <TextField.Root
            size="2"
            placeholder="entity tags (comma-separated, e.g. luna, tea)"
            value={tagsText}
            onChange={(e) => setTagsText(e.target.value)}
            style={{ marginBottom: 8 }}
          />
          <Flex gap="4" align="center" mb="3" wrap="wrap">
            <Box style={{ minWidth: 180 }}>
              <Text size="1" color="gray">Valence: {valence.toFixed(2)}</Text>
              <Slider
                value={[valence]}
                onValueChange={(v) => setValence(v[0])}
                min={-1} max={1} step={0.05}
              />
            </Box>
            <Box style={{ minWidth: 180 }}>
              <Text size="1" color="gray">Confidence: {confidence.toFixed(2)}</Text>
              <Slider
                value={[confidence]}
                onValueChange={(v) => setConfidence(v[0])}
                min={0} max={1} step={0.05}
              />
            </Box>
            <Box>
              <Text size="1" color="gray" style={{ display: "block" }}>Source</Text>
              <Select.Root
                size="1"
                value={sourceRole}
                onValueChange={(v) => setSourceRole(v as typeof sourceRole)}
              >
                <Select.Trigger />
                <Select.Content>
                  <Select.Item value="manual">manual</Select.Item>
                  <Select.Item value="user">user</Select.Item>
                  <Select.Item value="assistant">assistant</Select.Item>
                </Select.Content>
              </Select.Root>
            </Box>
          </Flex>
          <Flex gap="2">
            <Button size="2" onClick={handleUpsert} disabled={!factText.trim() || saving}>
              {saving ? "Saving…" : "Save fact"}
            </Button>
            <Button size="2" variant="soft" color="gray" onClick={() => setAdding(false)}>
              Cancel
            </Button>
          </Flex>
        </Box>
      )}

      {loading ? (
        <Text size="2" color="gray">Loading…</Text>
      ) : rows.length === 0 ? (
        <Text size="2" color="gray" style={{ fontStyle: "italic" }}>
          {mode === "search"
            ? `No facts match "${search}". Try fewer terms.`
            : "No episodic facts yet. The LOCOMO worker writes here after 30s of chat idle, or add one manually."}
        </Text>
      ) : (
        <Flex direction="column" gap="2">
          {rows.map((r) => (
            <EpisodicCard
              key={r.point_id}
              row={r}
              showScore={mode === "search"}
              onDelete={() => handleDelete(r.point_id)}
            />
          ))}
        </Flex>
      )}
    </Box>
  );
}
