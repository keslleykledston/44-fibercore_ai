import { defineConfig } from "@playwright/test";

// Interop ADR-0046: um único spec serial contra a pilha efêmera (scripts/interop46/run.sh). Cada prova leva minutos (ciclos de 15/30 s do Edge e janelas de observação).
export default defineConfig({
  testDir: ".",
  testMatch: /interop46\.spec\.ts/,
  timeout: 900_000,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: { baseURL: process.env.WEB_URL ?? "http://127.0.0.1:28490", locale: "pt-BR", timezoneId: "America/Manaus", colorScheme: "light", trace: "off" },
  projects: [{ name: "interop", use: { browserName: "chromium" } }],
});
