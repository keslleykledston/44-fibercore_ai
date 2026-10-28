import { defineConfig } from "@playwright/test";

// E2E contra a stack REAL (API + Postgres) com seed sintético: `make e2e-up && make e2e` (ver docs/engineering/SCREENSHOT_AND_HOWTO_PIPELINE.md).
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  workers: 1,
  retries: process.env.CI ? 1 : 0, // 1 flake observado (2 em ~10 execuções locais) no teste de aprovação de vínculos; investigar (KNOWN_ISSUES)
  reporter: [["list"]],
  use: {
    baseURL: process.env.WEB_URL ?? "http://127.0.0.1:3000",
    locale: "pt-BR",
    timezoneId: "America/Manaus",
    colorScheme: "light",
    trace: "retain-on-failure",
  },
  // Capturas primeiro (estado do seed intacto), depois os testes funcionais que mutam dados.
  projects: [
    { name: "capturas", testMatch: /help-screenshots\.spec\.ts/, use: { browserName: "chromium" } },
    { name: "funcional", testMatch: /app\.spec\.ts/, dependencies: ["capturas"], use: { browserName: "chromium" } },
  ],
});
