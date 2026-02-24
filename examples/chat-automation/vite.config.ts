import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const apiTarget = `http://localhost:${process.env.VITE_API_PORT || "8000"}`;

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5174,
    proxy: {
      "/api": apiTarget,
      "/health": apiTarget,
    },
  },
});
