/**
 * Shared HTTP client for authenticated REST calls.
 *
 * Desktop requests attach the persisted access token as
 * `Authorization: Bearer ...`. The hosted web app keeps cookie + CSRF
 * compatibility. Throws `ApiError` on non-2xx so callers can branch on
 * `status`.
 */
import { BACKEND_URL } from "@Shore/constants/backend.constant";
import { isTauri } from "@Shore/utils/tauri.util";

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    super(`HTTP ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

const ACCESS_TOKEN_STORAGE_KEY = "shore_access_token";
const IS_DESKTOP = isTauri();

function loadAccessToken(): string | null {
  try {
    return window.localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

// Module-level credentials avoid threading AuthContext through every
// service. The access token is persisted so the desktop session survives
// app restarts; the hosted web origin never receives or stores one.
let _accessToken: string | null = IS_DESKTOP ? loadAccessToken() : null;
let _csrfToken: string | null = null;

export function setAccessToken(token: string | null): void {
  _accessToken = token;
  try {
    if (token) {
      window.localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, token);
    } else {
      window.localStorage.removeItem(ACCESS_TOKEN_STORAGE_KEY);
    }
  } catch {
    // Some embedded/private contexts disable persistent storage. The
    // in-memory token still keeps the current app session functional.
  }
}

export function getAccessToken(): string | null {
  return _accessToken;
}

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

export function notifyUnauthorized(): void {
  _onUnauthorized.forEach((fn) => fn());
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
  if (_accessToken) {
    headers.set("Authorization", `Bearer ${_accessToken}`);
  }
  if (!_accessToken && _isWrite(init?.method) && _csrfToken) {
    headers.set("X-CSRF-Token", _csrfToken);
  }

  const res = await fetch(`${BACKEND_URL}${path}`, {
    // Never send ambient cookies from Tauri, including cookies left by
    // versions that predate Bearer auth. The hosted web app still needs
    // credentials for its HttpOnly-cookie flow.
    credentials: IS_DESKTOP ? "omit" : "include",
    ...init,
    headers,
  });

  if (res.status === 401) {
    notifyUnauthorized();
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

/**
 * Fetch a protected binary resource (e.g. `/api/images/{id}`) with the same
 * auth semantics as `apiFetch` and return a blob object URL for `<img src>`.
 *
 * Needed because a plain `<img src>` can't attach the desktop Bearer header —
 * only cookies ride along automatically. Returns `null` on any failure
 * (401/404/network) so callers can drop the image instead of rendering a
 * broken one.
 */
export async function fetchBlobUrl(path: string): Promise<string | null> {
  try {
    const headers = new Headers();
    if (_accessToken) {
      headers.set("Authorization", `Bearer ${_accessToken}`);
    }
    const res = await fetch(`${BACKEND_URL}${path}`, {
      credentials: IS_DESKTOP ? "omit" : "include",
      headers,
    });
    if (res.status === 401) {
      notifyUnauthorized();
    }
    if (!res.ok) {
      return null;
    }
    return URL.createObjectURL(await res.blob());
  } catch {
    return null;
  }
}
