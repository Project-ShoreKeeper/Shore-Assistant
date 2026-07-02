/**
 * Auth REST client — talks to /api/auth/*.
 */
import { BACKEND_URL } from "@Shore/constants/backend.constant";
import { apiFetch } from "./http.service";

export type Role = "admin" | "user";

export interface MeResponse {
  email: string;
  role: Role;
  csrf: string;
}

export interface TokenExchangeResponse extends MeResponse {
  access_token: string;
  token_type: "bearer";
}

export const authService = {
  /** GET /me — throws ApiError(401) when no/expired session. */
  me(): Promise<MeResponse> {
    return apiFetch<MeResponse>("/api/auth/me");
  },

  /** POST /logout — revokes the server session. */
  logout(): Promise<{ ok: true }> {
    return apiFetch<{ ok: true }>("/api/auth/logout", { method: "POST" });
  },

  /** Hard navigate to /api/auth/login (Authlib starts the OAuth dance). */
  startLoginRedirect(): void {
    window.location.href = `${BACKEND_URL}/api/auth/login`;
  },

  /**
   * Desktop (Tauri) login: opens the backend's OAuth start URL in the
   * system browser via the opener plugin — never navigates the webview.
   * Google disallows OAuth consent inside an embedded webview, and the
   * callback deep-links back into the app (see deep-link.service.ts).
   */
  async startDesktopLogin(): Promise<void> {
    const { openUrl } = await import("@tauri-apps/plugin-opener");
    await openUrl(`${BACKEND_URL}/api/auth/login?client=desktop`);
  },

  /**
   * POST /exchange — redeems the one-time desktop deep-link token
   * (`shore-assistant://auth?xchg=<token>`) for an opaque Bearer access
   * token. Throws ApiError(401) on an invalid/expired/used token.
   */
  exchange(token: string): Promise<TokenExchangeResponse> {
    return apiFetch<TokenExchangeResponse>("/api/auth/exchange", {
      method: "POST",
      body: JSON.stringify({ token }),
    });
  },
};
