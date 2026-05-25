import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { viteSingleFile } from "vite-plugin-singlefile";
import path from "node:path";

export default defineConfig({
  plugins: [react(), viteSingleFile()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  build: {
    target: "es2022",
    cssCodeSplit: false,
    assetsInlineLimit: Infinity,
    rollupOptions: {
      output: {
        inlineDynamicImports: true,
      },
    },
  },
});
