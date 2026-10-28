/**
 * Capturas REAIS da aplicação integrada (Next.js + API + Postgres) com seed sintético (scripts/seed_demo.py).
 * Gera docs/help/assets/<categoria>/<slug>/{desktop,mobile}.png. Dados de tempo relativo ficam mascarados.
 */
import path from "node:path";
import { expect, test } from "@playwright/test";
import { login } from "./helpers";

const ROOT = path.resolve(__dirname, "..", "..", "..", "docs", "help", "assets");
const screens = [
  { slug: "visao-geral/visao-geral", route: "/", ready: "kpis" },
  { slug: "rede/consultar-onu", route: "/rede", ready: "onu-inventory-ready" },
  { slug: "noc/acompanhar-incidente", route: "/noc", ready: "incident-queue" },
  { slug: "assinantes/importar-e-revisar-vinculos", route: "/assinantes", ready: "association-list" },
  { slug: "operacoes/acompanhar-operacoes", route: "/operacoes", ready: "jobs-table" },
  { slug: "administracao/saude-modulos", route: "/administracao/modulos", ready: "modules-table" },
  { slug: "conta/ativar-verificacao-em-duas-etapas", route: "/conta/seguranca", ready: "security-page" },
  { slug: "ajuda/central-de-ajuda", route: "/ajuda", ready: "help-list" },
];
const viewports = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "mobile", width: 390, height: 844 },
];

for (const vp of viewports) {
  test.describe(`capturas ${vp.name}`, () => {
    test.use({ viewport: { width: vp.width, height: vp.height }, deviceScaleFactor: 1 });
    for (const s of screens) {
      test(`${s.slug} - ${vp.name}`, async ({ page }) => {
        await login(page);
        await page.goto(s.route);
        await expect(page.getByTestId(s.ready)).toBeVisible();
        await page.evaluate(() => document.fonts.ready);
        await page.screenshot({
          path: path.join(ROOT, s.slug, `${vp.name}.png`),
          fullPage: true,
          animations: "disabled",
          mask: [page.getByTestId("freshness")],
          maskColor: "#C9D1DA",
        });
      });
    }
  });
}
