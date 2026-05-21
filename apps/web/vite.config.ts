import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173
  },
  build: {
    chunkSizeWarningLimit: 800,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) {
            return undefined;
          }
          if (id.includes("/firebase/")) {
            return "vendor-firebase";
          }
          if (id.includes("/element-plus/")) {
            return "vendor-element-plus";
          }
          if (id.includes("/vue-router/")) {
            return "vendor-router";
          }
          return "vendor-shared";
        },
      },
    },
  },
  test: {
    environment: "happy-dom",
    globals: true,
    exclude: ["e2e/**", "**/e2e/**"]
  }
});
