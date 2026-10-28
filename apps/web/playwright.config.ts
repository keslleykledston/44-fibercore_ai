import { defineConfig } from "@playwright/test";

// E2E contra a stack REAL (API + Postgres) com seed sintético: `make e2e-up && make e2e` (ver docs/engineering/SCREENSHOT_AND_HOWTO_PIPELINE.md).
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.WEB_URL ?? "http://127.0.0.1:3000",
    locale: "pt-BR",
    timezoneId: "America/Manaus",
    colorScheme: "light",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
