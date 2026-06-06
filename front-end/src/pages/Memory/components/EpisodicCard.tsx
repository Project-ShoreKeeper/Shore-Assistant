import { useState } from "react";
import { Box, Flex, Text, Button, Badge } from "@radix-ui/themes";
import type { EpisodicRow } from "@Shore/services/memory-api.service";

interface Props {
  row: EpisodicRow;
  showScore?: boolean;
  onDelete: () => void;
}

function fmtTime(epoch: number | null): string {
  if (!epoch) return "—";
  return new Date(epoch * 1000).toLocaleString();
}

function valencePill(v: number) {
  const color = v > 0.1 ? "green" : v < -0.1 ? "red" : "gray";
  return (
    <Badge size="1" color={color} variant="soft">
      val {v >= 0 ? "+" : ""}{v.toFixed(2)}
    </Badge>
  );
}

export default function EpisodicCard({ row, showScore, onDelete }: Props) {
  const [confirmDel, setConfirmDel] = useState(false);
  const arm = () => {
    setConfirmDel(true);
    setTimeout(() => setConfirmDel(false), 3000);
  };

  return (
    <Box
      style={{
        background: "var(--gray-2)",
        border: "1px solid var(--gray-5)",
        borderRadius: 8,
        padding: 12,
      }}
    >
      <Text size="2" style={{ display: "block", marginBottom: 8 }}>
        {row.fact}
      </Text>
      <Flex gap="2" align="center" wrap="wrap" mb="2">
        {row.entity_tags.map((t) => (
          <Badge key={t} size="1" color="indigo" variant="soft">{t}</Badge>
        ))}
        {valencePill(row.valence)}
        {showScore && (
          <Badge size="1" color="cyan" variant="soft">
            score {row.score.toFixed(3)}
          </Badge>
        )}
      </Flex>
      <Flex justify="between" align="center">
        <Text size="1" color="gray">
          {fmtTime(row.created_at)} · conf {row.confidence.toFixed(2)} · src {row.source_role} ·{" "}
          <span style={{ fontFamily: "monospace" }} title={row.point_id}>
            #{row.point_id.slice(0, 8)}
          </span>
        </Text>
        <Button
          size="1"
          variant="ghost"
          color="red"
          onClick={() => (confirmDel ? onDelete() : arm())}
        >
          {confirmDel ? "confirm delete?" : "delete"}
        </Button>
      </Flex>
    </Box>
  );
}
