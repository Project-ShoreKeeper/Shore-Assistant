import { Navigate, useLocation } from "react-router-dom";

import { useAuth } from "@Shore/contexts/AuthContext";
import type { Role } from "@Shore/services/auth.service";

interface Props {
  /** Optional minimum role. Omit to allow any authenticated user. */
  role?: Role;
  children: React.ReactNode;
}

/**
 * Wraps a route. Redirects to /login when unauthenticated, or renders
 * a 403 when the user is signed in but lacks the required role.
 */
export default function AuthGuard({ role, children }: Props) {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    // Lightweight placeholder — auth resolution should be sub-second.
    return null;
  }
  if (!user) {
    return (
      <Navigate
        to="/login"
        state={{ from: location.pathname + location.search }}
        replace
      />
    );
  }
  if (role === "admin" && user.role !== "admin") {
    return <Navigate to="/403" replace />;
  }
  return <>{children}</>;
}
