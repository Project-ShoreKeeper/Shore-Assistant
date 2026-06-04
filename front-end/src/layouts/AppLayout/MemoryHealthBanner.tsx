import { useEffect, useState } from "react";

type Health = {
  status: string;
  memory: { redis: string; postgres: string; qdrant: string };
};

export function MemoryHealthBanner() {
  const [h, setH] = useState<Health | null>(null);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const r = await fetch("/health");
        const json = (await r.json()) as Health;
        if (!cancelled) setH(json);
      } catch {
        if (!cancelled) {
          setH({
            status: "unhealthy",
            memory: { redis: "down", postgres: "down", qdrant: "down" },
          });
        }
      }
    };
    void poll();
    const id = setInterval(poll, 30_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  if (!h || h.status === "healthy") return null;

  const down = Object.entries(h.memory)
    .filter(([, v]) => v === "down")
    .map(([k]) => k);
  const tone =
    h.status === "unhealthy"
      ? "bg-red-200 text-red-900"
      : "bg-yellow-200 text-yellow-900";
  return (
    <div className={`${tone} px-3 py-1.5 text-sm`}>
      Memory degraded: {down.join(", ")} offline. Chat continues with
      reduced context.
    </div>
  );
}
