import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// Workshop notes:
// - base "/app/" must match the /app/ route in workbench/nginx.conf.
// - host/allowedHosts let the workbench proxy (and PS Portal) reach the dev server.
// - usePolling is needed for HMR on Docker volumes mounted from macOS/Windows.
// - In the workshop, the browser calls /api/* on the workbench origin and nginx routes it to the
//   backend container, so no dev-server proxy is needed there. The proxy below only matters when
//   running the frontend outside Docker (`make dev`).
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const target = env.VITE_API_BASE_URL || "http://127.0.0.1:8040";

  return {
    base: env.VITE_BASE_PATH || "/",
    plugins: [react()],
    server: {
      host: true,
      allowedHosts: true,
      watch: { usePolling: !!env.VITE_USE_POLLING },
      proxy: {
        "/api": {
          target,
          changeOrigin: true,
        },
      },
    },
  };
});
