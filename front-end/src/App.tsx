import { BrowserRouter, useLocation } from "react-router-dom";
import PublicRoutes from "./routers/PublicRoutes";
import { Theme, ThemePanel } from "@radix-ui/themes";
import { AuthProvider } from "@Shore/contexts/AuthContext";

function AppContent() {
  const location = useLocation();
  const isHudWindow = location.pathname === "/hud";

  return (
    <Theme accentColor="sky">
      {isHudWindow ? (
        <PublicRoutes />
      ) : (
        <AuthProvider>
          <PublicRoutes />
        </AuthProvider>
      )}
      {!isHudWindow && <ThemePanel defaultOpen={false} />}
    </Theme>
  );
}

function App() {
  return (
    <BrowserRouter>
      <AppContent />
    </BrowserRouter>
  );
}

export default App;
