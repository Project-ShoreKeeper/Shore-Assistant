import {
  createContext, useCallback, useContext, useEffect, useState,
} from "react";

import { authService, type MeResponse, type Role } from "@Shore/services/auth.service";
import { ApiError, onUnauthorized, setCsrfToken } from "@Shore/services/http.service";

export interface AuthUser {
  email: string;
  role: Role;
}

interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean;
  /** Hard-redirect to the backend OAuth start endpoint. */
  login: () => void;
  /** Server logout + local clear. */
  logout: () => Promise<void>;
  /** Re-fetch /me — call after a window regains focus, etc. */
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  const apply = useCallback((me: MeResponse | null) => {
    if (me) {
      setUser({ email: me.email, role: me.role });
      setCsrfToken(me.csrf);
    } else {
      setUser(null);
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

  const login = useCallback(() => {
    authService.startLoginRedirect();
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
    <AuthContext.Provider value={{ user, loading, login, logout, refresh }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
