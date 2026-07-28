import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dev server proxies /api to the FastAPI service so the browser sees a
// same-origin app. That keeps the default API base a plain relative "/api/v1"
// and means CORS never enters the picture during development.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.AGENT_KIT_API ?? "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
