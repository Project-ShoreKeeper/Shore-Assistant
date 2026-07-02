import {
  createContext, useCallback, useContext, useEffect, useState,
} from "react";

import { authService, type MeResponse, type Role } from "@Shore/services/auth.service";
import { registerAuthDeepLink } from "@Shore/services/deep-link.service";
import {
  ApiError,
  onUnauthorized,
  setAccessToken,
  setCsrfToken,
} from "@Shore/services/http.service";
import { isTauri } from "@Shore/utils/tauri.util";

export interface AuthUser {
  email: string;
  role: Role;
}

interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean;
  /** Web: hard-redirect to the backend OAuth start endpoint. Desktop
   *  (Tauri): opens the same endpoint in the system browser instead. */
  login: () => void;
  /** Server logout + local clear. */
  logout: () => Promise<void>;
  /** Re-fetch /me — call after a window regains focus, etc. */
  refresh: () => Promise<void>;
  /** Desktop-only: set when the `xchg` deep-link exchange fails
   *  (expired/already-consumed token). Null otherwise. */
  desktopAuthError: string | null;
  /** Clears desktopAuthError — call before retrying login. */
  clearDesktopAuthError: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [desktopAuthError, setDesktopAuthError] = useState<string | null>(null);

  const apply = useCallback((me: MeResponse | null) => {
    if (me) {
      setUser({ email: me.email, role: me.role });
      setCsrfToken(me.csrf);
    } else {
      setUser(null);
      setAccessToken(null);
      setCsrfToken(null);
    }
  }, []);

  const refresh = useCallback(async () => {
    try {
      const me = await authService.me();
      apply(me);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        apply(null);
      } else {
        // Network or 5xx — keep last known state so a transient blip
        // doesn't blow away the session UX. The next /me request will
        // self-correct.
        console.warn("[Auth] refresh failed:", e);
      }
    } finally {
      setLoading(false);
    }
  }, [apply]);

  // Initial fetch on mount.
  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Any 401 anywhere in the app clears auth state — AuthGuard reacts.
  useEffect(() => {
    return onUnauthorized(() => apply(null));
  }, [apply]);

  // Desktop-only: registers the `shore-assistant://auth?xchg=...` deep
  // link handler once at startup (also covers the cold-start "app was
  // launched by the link" case). No-op outside Tauri.
  useEffect(() => {
    let cancelled = false;
    let unlisten: (() => void) | undefined;

    const handleToken = (token: string) => {
      void (async () => {
        try {
          const result = await authService.exchange(token);
          setAccessToken(result.access_token);
          apply(result);
          setDesktopAuthError(null);
        } catch (e) {
          if (e instanceof ApiError && e.status === 401) {
            setDesktopAuthError("Login session expired, please try again.");
          } else {
            console.warn("[Auth] desktop exchange failed:", e);
          }
        }
      })();
    };

    void registerAuthDeepLink(handleToken).then((cleanup) => {
      if (cancelled) cleanup();
      else unlisten = cleanup;
    });

    return () => {
      cancelled = true;
      unlisten?.();
    };
  }, [apply]);

  const login = useCallback(() => {
    if (isTauri()) {
      void authService.startDesktopLogin();
    } else {
      authService.startLoginRedirect();
    }
  }, []);

  const clearDesktopAuthError = useCallback(() => {
    setDesktopAuthError(null);
  }, []);

  const logout = useCallback(async () => {
    try {
      await authService.logout();
    } catch (e) {
      // Even if the server call fails, clear locally so the user isn't
      // stuck on a broken page.
      console.warn("[Auth] logout server call failed:", e);
    }
    apply(null);
  }, [apply]);

  return (
    <AuthContext.Provider
      value={{
        user, loading, login, logout, refresh,
        desktopAuthError, clearDesktopAuthError,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
