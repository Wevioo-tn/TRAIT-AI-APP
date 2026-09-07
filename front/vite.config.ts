/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Bound to 0.0.0.0 with a fixed port so the Vite dev server is reachable
// from outside the container when run via docker-compose.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    strictPort: true,
    // The source tree is bind-mounted from the Windows host (docker-compose.yml);
    // native fs-change events don't cross that mount, so chokidar's default
    // watcher silently never fires and Vite keeps serving stale modules.
    // Polling is the standard workaround for this exact Docker Desktop setup.
    watch: {
      usePolling: true,
      interval: 300,
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    globals: true,
  },
});
