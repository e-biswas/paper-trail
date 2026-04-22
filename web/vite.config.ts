import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"

const BACKEND = process.env.VITE_BACKEND ?? "http://127.0.0.1:8080"

// Vite dev-server proxy keeps WebSocket + REST calls on the same origin so
// CORS / credential handling stays simple during development.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/ws": { target: BACKEND, ws: true, changeOrigin: true },
      "/runs": { target: BACKEND, changeOrigin: true },
      "/sessions": { target: BACKEND, changeOrigin: true },
      "/usage": { target: BACKEND, changeOrigin: true },
      "/papers": { target: BACKEND, changeOrigin: true },
      "/repos": { target: BACKEND, changeOrigin: true },
      "/healthz": { target: BACKEND, changeOrigin: true },
    },
  },
})
