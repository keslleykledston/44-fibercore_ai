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
    { name: "puros", testMatch: /(optics|optics-contrast|optics-colormix|quality-source|olt-panel-pure|edge-diagnostic-pure|device-assets-pure)\.spec\.ts/, use: { browserName: "chromium" } },   // funções puras: sem navegador nem API
    { name: "capturas", testMatch: /help-(screenshots|speed|quality)\.spec\.ts/, use: { browserName: "chromium" } },
    { name: "funcional", testMatch: /app\.spec\.ts/, dependencies: ["capturas"], use: { browserName: "chromium" } },
    // Por último: reconhecer o incidente demo muda o estado que os testes acima assumem (não reconhecido).
    { name: "posteriores", testMatch: /noc-ack-and-search\.spec\.ts/, dependencies: ["funcional"], use: { browserName: "chromium" } },
    { name: "inspetor", testMatch: /onu-(quick|workspace)\.spec\.ts|(speed|quality|ping)\.spec\.ts/, dependencies: ["funcional"], use: { browserName: "chromium" } },
    // Recuo com a flag `onu_quick_inspector` DESLIGADA no provedor: sem dependência de `funcional` (que exige a flag ligada). Só roda com ASSINANTE_HISTORICO_FLAG_OFF=1:
    // npx playwright test --project=recuo-historico
    { name: "recuo-historico", testMatch: /assinante-historico-flag\.spec\.ts/, use: { browserName: "chromium" } },
    // Recuo da ONU 360° enxuta com a flag `onu_quick_inspector` DESLIGADA: ONU360_FLAG_OFF=1 npx playwright test --project=recuo-onu360
    { name: "recuo-onu360", testMatch: /onu360-flag\.spec\.ts/, use: { browserName: "chromium" } },
    { name: "catalogo", testMatch: /catalogo\.spec\.ts/, dependencies: ["funcional"], use: { browserName: "chromium" } },
    // Recuo do catálogo de equipamentos com a flag `device_assets` DESLIGADA: DEVICE_ASSETS_FLAG_OFF=1 npx playwright test --project=recuo-catalogo
    { name: "recuo-catalogo", testMatch: /catalogo-flag\.spec\.ts/, use: { browserName: "chromium" } },
    { name: "frota", testMatch: /frota\.spec\.ts/, dependencies: ["funcional"], use: { browserName: "chromium" } },
    // Recuo da Frota de OLTs com a flag `fleet_manager` DESLIGADA: FLEET_FLAG_OFF=1 npx playwright test --project=recuo-frota
    { name: "recuo-frota", testMatch: /frota-flag\.spec\.ts/, use: { browserName: "chromium" } },
    { name: "perfis", testMatch: /perfis\.spec\.ts/, dependencies: ["funcional"], use: { browserName: "chromium" } },
    // Recuo com a flag `profile_studio` DESLIGADA: PERFIS_FLAG_OFF=1 npx playwright test --project=recuo-perfis
    { name: "recuo-perfis", testMatch: /perfis-flag\.spec\.ts/, use: { browserName: "chromium" } },
    { name: "pendentes", testMatch: /pendentes\.spec\.ts/, dependencies: ["funcional"], use: { browserName: "chromium" } },
    // Recuo com a flag `onu_discovery` DESLIGADA: PENDENTES_FLAG_OFF=1 npx playwright test --project=recuo-pendentes
    { name: "recuo-pendentes", testMatch: /pendentes-flag\.spec\.ts/, use: { browserName: "chromium" } },
    { name: "painel", testMatch: /olt-painel\.spec\.ts/, dependencies: ["funcional"], use: { browserName: "chromium" } },
    { name: "aparelho", testMatch: /ont-sidebar\.spec\.ts/, dependencies: ["funcional"], use: { browserName: "chromium" } },
    { name: "consultas", testMatch: /olt-queries\.spec\.ts/, dependencies: ["funcional"], use: { browserName: "chromium" } },
  ],
});
