import { BrowserRouter } from "react-router-dom";
import PublicRoutes from "./routers/PublicRoutes";
import { Theme, ThemePanel } from "@radix-ui/themes";
import { AuthProvider } from "@Shore/contexts/AuthContext";

function App() {
  return (
    <BrowserRouter>
      <Theme accentColor="sky">
        <AuthProvider>
          <PublicRoutes />
        </AuthProvider>
        <ThemePanel defaultOpen={false} />
      </Theme>
    </BrowserRouter>
  );
}

export default App;
