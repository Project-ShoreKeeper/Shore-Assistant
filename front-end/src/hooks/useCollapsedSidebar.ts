import { useCallback, useEffect, useState } from "react";

/**
 * Persisted collapse state for a sidebar, keyed by storageKey.
 * Returns [collapsed, toggle] — toggle also writes to localStorage.
 * Falls back to `false` (expanded) when storage is unavailable or empty.
 */
export function useCollapsedSidebar(storageKey: string): [boolean, () => void] {
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    try {
      return window.localStorage.getItem(storageKey) === "1";
    } catch {
      return false;
    }
  });

  useEffect(() => {
    try {
      window.localStorage.setItem(storageKey, collapsed ? "1" : "0");
    } catch {
      // localStorage disabled / quota — ignore, state still works in-memory.
    }
  }, [storageKey, collapsed]);

  const toggle = useCallback(() => setCollapsed((c) => !c), []);

  return [collapsed, toggle];
}
