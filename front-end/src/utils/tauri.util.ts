/**
 * Runtime "am I in Tauri?" guard.
 *
 * Used to gate every Tauri-only code path (system-browser OAuth open,
 * deep-link registration) behind a check + dynamic import so the plain
 * web bundle never pulls in Tauri JS at load time.
 */
export function isTauri(): boolean {
  if (typeof window === "undefined") return false;
  const w = window as unknown as Record<string, unknown>;
  return "__TAURI_INTERNALS__" in w || "__TAURI__" in w;
}
