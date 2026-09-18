import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "/app/",
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks: {
          "kumo-vendor": ["@cloudflare/kumo"],
          "icons-vendor": ["@phosphor-icons/react"],
        },
      },
    },
  },
});
