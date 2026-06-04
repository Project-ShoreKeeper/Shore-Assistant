import { useEffect, useState } from "react";
import { BACKEND_URL } from "../../constants/backend.constant";

type LayerStatus = "ok" | "down";
type Status = "healthy" | "degraded" | "unhealthy";

type Health = {
  status: Status;
  memory: { redis: LayerStatus; postgres: LayerStatus; qdrant: LayerStatus };
};

const POLL_INTERVAL_MS = 30_000;
const FETCH_TIMEOUT_MS = 5_000;

const LAYER_LABEL: Record<keyof Health["memory"], string> = {
  redis: "Redis",
  postgres: "Postgres",
  qdrant: "Qdrant",
};

const UNHEALTHY_FALLBACK: Health = {
  status: "unhealthy",
  memory: { redis: "down", postgres: "down", qdrant: "down" },
};


export function MemoryHealthBanner() {
  const [h, setH] = useState<Health | null>(null);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const r = await fetch(`${BACKEND_URL}/health`, {
          signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
        });
        const json = (await r.json()) as Health;
        if (!cancelled) setH(json);
      } catch {
        if (!cancelled) setH(UNHEALTHY_FALLBACK);
      }
    };
    void poll();
    const id = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  if (!h || h.status === "healthy") return null;

  const down = (Object.keys(h.memory) as Array<keyof Health["memory"]>)
    .filter((k) => h.memory[k] === "down")
    .map((k) => LAYER_LABEL[k]);

  const isUnhealthy = h.status === "unhealthy";
  const tone = isUnhealthy
    ? "bg-red-200 text-red-900 border-l-4 border-red-700"
    : "bg-yellow-200 text-yellow-900 border-l-4 border-yellow-700";
  const severity = isUnhealthy ? "Critical" : "Warning";
  const suffix = isUnhealthy
    ? "Chat history unavailable — recent turns will not be remembered."
    : "Chat continues with reduced context.";

  return (
    <div
      role={isUnhealthy ? "alert" : "status"}
      aria-live="polite"
      className={`${tone} px-3 py-1.5 text-sm`}
    >
      {severity}: memory degraded — {down.join(", ")} offline. {suffix}
    </div>
  );
}
