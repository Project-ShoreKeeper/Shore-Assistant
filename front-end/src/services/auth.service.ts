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

export const authService = {
  /** GET /me — throws ApiError(401) when no/expired session. */
  me(): Promise<MeResponse> {
    return apiFetch<MeResponse>("/api/auth/me");
  },

  /** POST /logout — clears server session + cookie. */
  logout(): Promise<{ ok: true }> {
    return apiFetch<{ ok: true }>("/api/auth/logout", { method: "POST" });
  },

  /** Hard navigate to /api/auth/login (Authlib starts the OAuth dance). */
  startLoginRedirect(): void {
    window.location.href = `${BACKEND_URL}/api/auth/login`;
  },
};
