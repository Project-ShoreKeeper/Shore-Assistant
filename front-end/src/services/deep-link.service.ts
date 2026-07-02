/**
 * Desktop-only: registers the `shore-assistant://auth?xchg=<token>` deep
 * link handler used by the Tauri OAuth exchange flow (see
 * docs/superpowers/specs/2026-07-02-tauri-desktop-client-design.md).
 *
 * No-op outside Tauri. Web bundle never imports the deep-link plugin
 * package because the dynamic import only fires when `isTauri()` is true.
 */
import { isTauri } from "@Shore/utils/tauri.util";

function extractExchangeToken(url: string): string | null {
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== "shore-assistant:") return null;
    return parsed.searchParams.get("xchg");
  } catch {
    return null;
  }
}

/**
 * Registers the deep-link listener and handles the cold-start "initial
 * URL" case (the plugin's `getCurrent()`). Calls `onToken` for every
 * `xchg` token seen, past or future. Returns a cleanup function — always
 * safe to call, even if this resolved to a no-op outside Tauri.
 */
export async function registerAuthDeepLink(
  onToken: (token: string) => void,
): Promise<() => void> {
  if (!isTauri()) return () => {};

  const { onOpenUrl, getCurrent } = await import("@tauri-apps/plugin-deep-link");

  const handleUrls = (urls: string[] | null | undefined) => {
    for (const url of urls ?? []) {
      const token = extractExchangeToken(url);
      if (token) onToken(token);
    }
  };

  // Cold start: the app may have been launched *by* the deep link.
  handleUrls(await getCurrent());

  return await onOpenUrl((urls) => handleUrls(urls));
}
