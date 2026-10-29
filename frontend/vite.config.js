
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/food": "http://127.0.0.1:8000",
      "/ngos": "http://127.0.0.1:8000"
    }
  }
});

