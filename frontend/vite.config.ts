import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    // macOS bind mounts do not deliver inotify events — polling is the price
    // of docker-native dev (DEVELOPMENT.md §"Five details", ADR-0010).
    watch: { usePolling: true, interval: 300 },
    hmr: { clientPort: 5173 },
    // theme.css imports the read-only /design mount; Vite's fs guard would
    // otherwise refuse to serve outside the project root.
    fs: { allow: [".", "../design"] },
  },
});
