import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./", import.meta.url)),
    },
  },
  test: {
    environment: "happy-dom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    // Keep Playwright's `e2e/` suite separate from unit/component tests.
    exclude: ["node_modules", "dist", ".next", "e2e/**"],
    css: true,
    typecheck: {
      tsconfig: "./tsconfig.test.json",
    },
  },
});
