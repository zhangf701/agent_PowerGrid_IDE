import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// ★ 开发期把网关端点代理到 127.0.0.1:8765（同源，无 CORS）；
//   MVP 的经验：fetch 相对路径 + 同源 = 最省事的部署形态，dev 与 prod 行为一致。
const GATEWAY = "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "^/(health|environment|skills|cases|contracts|sessions|modules|checks|ui)": {
        target: GATEWAY,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test-setup.ts",
  },
});
