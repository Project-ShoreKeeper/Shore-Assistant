import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: "0.0.0.0",  // Listen on all interfaces (accessible via Tailscale)
    port: 5173,
  },
  resolve: {
    alias: {
      "@Shore": path.resolve(__dirname, "./src"),
    },
  },
});
