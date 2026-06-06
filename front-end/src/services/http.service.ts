/**
 * Shared HTTP client for authenticated REST calls.
 *
 * Sends cookies via `credentials: "include"` and attaches the CSRF
 * token from AuthContext on state-changing requests. Throws
 * `ApiError` on non-2xx so the caller can branch on `status`.
 */
import { BACKEND_URL } from "@Shore/constants/backend.constant";

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    super(`HTTP ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

// A module-level CSRF token, populated by AuthContext on /me. This
// avoids threading a context through every service call.
let _csrfToken: string | null = null;

export function setCsrfToken(token: string | null): void {
  _csrfToken = token;
}

export function getCsrfToken(): string | null {
  return _csrfToken;
}

// Listeners for 401 — AuthContext registers one so it can clear the user
// and route to /login from anywhere a request originates.
type UnauthorizedListener = () => void;
const _onUnauthorized: Set<UnauthorizedListener> = new Set();

export function onUnauthorized(fn: UnauthorizedListener): () => void {
  _onUnauthorized.add(fn);
  return () => _onUnauthorized.delete(fn);
}

function _isWrite(method?: string): boolean {
  const m = (method || "GET").toUpperCase();
  return m === "POST" || m === "PUT" || m === "PATCH" || m === "DELETE";
}

export async function apiFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const headers = new Headers(init?.headers || {});
  if (!headers.has("Content-Type") && init?.body !== undefined) {
    headers.set("Content-Type", "application/json");
  }
  if (_isWrite(init?.method) && _csrfToken) {
    headers.set("X-CSRF-Token", _csrfToken);
  }

  const res = await fetch(`${BACKEND_URL}${path}`, {
    credentials: "include",
    ...init,
    headers,
  });

  if (res.status === 401) {
    _onUnauthorized.forEach((fn) => fn());
  }

  if (!res.ok) {
    let detail: unknown = res.statusText;
    try {
      detail = await res.json();
    } catch {
      /* body wasn't JSON; keep statusText */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) {
    return undefined as T;
  }
  return res.json() as Promise<T>;
}
