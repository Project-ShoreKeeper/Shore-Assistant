import React from "react";
import { BrowserRouter } from "react-router-dom";
import PublicRoutes from "./routers/PublicRoutes";
import { Theme, ThemePanel } from "@radix-ui/themes";

function App() {
  return (
    <BrowserRouter>
      <Theme accentColor="sky">
        <PublicRoutes />
        <ThemePanel defaultOpen={false} />
      </Theme>
    </BrowserRouter>
  );
}

export default App;
