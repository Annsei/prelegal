import { defineConfig, devices } from "@playwright/test";

// Reserve a fixed port to keep the Playwright dev server deterministic.
const PORT = 3131;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: "list",
  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: {
    // Local dev uses `next dev` for fast reload. Set E2E_USE_BUILD=1 (or use the
    // `test:e2e:ci` script) to exercise the production build instead — this is
    // what CI runs so the tests reflect deployed behavior. The project is a
    // static export (output: "export"), which `next start` refuses to serve;
    // `serve` maps clean URLs to .html files the same way the FastAPI
    // fallback does in production.
    command: process.env.E2E_USE_BUILD
      ? `next build && serve -l ${PORT} out`
      : `next dev -p ${PORT}`,
    url: `http://localhost:${PORT}`,
    reuseExistingServer: !process.env.CI,
    stdout: "pipe",
    stderr: "pipe",
    timeout: 120_000,
  },
});
