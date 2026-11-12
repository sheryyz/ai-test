import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

// The build is committed to consenttrace/web/dist so judges can run the console without Node.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: "./",
  build: { outDir: "../consenttrace/web/dist", emptyOutDir: true, chunkSizeWarningLimit: 900 },
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
});
