import { useCallback, useEffect, useRef, useState } from "react";
import { fetchDashboard, type DashboardSnapshot } from "@Shore/services/dashboard.service";

const POLL_INTERVAL_MS = 5000;
const FAST_POLL_INTERVAL_MS = 1000;

/** True if any controllable service or worker is currently transitioning. */
function _anyTransitioning(snap: DashboardSnapshot | null): boolean {
  if (!snap) return false;
  for (const s of snap.services) {
    if (s.control?.transitioning) return true;
  }
  for (const d of snap.databases) {
    if (d.control?.transitioning) return true;
  }
  if (snap.workers.locomo.control?.transitioning) return true;
  if (snap.workers.canonicalizer.control?.transitioning) return true;
  return false;
}

export function useDashboardPoll() {
  const [data, setData] = useState<DashboardSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [paused, setPaused] = useState(() => document.hidden);
  const inFlight = useRef(false);
  const fastPollUntil = useRef<number>(0);

  const tick = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      const snap = await fetchDashboard();
      setData(snap);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
      inFlight.current = false;
    }
  }, []);

  /** Force one immediate refresh + ask the loop to poll fast for the next 30s. */
  const expedite = useCallback(() => {
    fastPollUntil.current = Date.now() + 30_000;
    tick();
  }, [tick]);

  useEffect(() => {
    const onVis = () => setPaused(document.hidden);
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, []);

  // Two-mode interval: fast while a service is transitioning (or a recent
  // expedite window is open), regular otherwise. Re-keys when transitioning
  // flips so the interval gets re-created at the right cadence.
  const transitioning = _anyTransitioning(data);
  const isWithinExpediteWindow = Date.now() < fastPollUntil.current;
  const intervalMs = (transitioning || isWithinExpediteWindow)
    ? FAST_POLL_INTERVAL_MS
    : POLL_INTERVAL_MS;

  useEffect(() => {
    tick();
    if (paused) return;
    const id = window.setInterval(tick, intervalMs);
    return () => window.clearInterval(id);
  }, [paused, tick, intervalMs]);

  return { data, error, loading, paused, refresh: tick, expedite };
}
