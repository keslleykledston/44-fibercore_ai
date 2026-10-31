/**
 * Capturas da ajuda "Como ler o diagnóstico de qualidade do serviço" (ADR-0039). Gera docs/help/assets/rede/qualidade-do-servico/*.png.
 * - desktop.png / mobile.png: estado REAL da aplicação integrada com seed sintético (leitura feita agora, sobre o aparelho demo: sem leitura do ACS, dados insuficientes).
 * - cenario-*.png: CENÁRIOS DE TESTE. A rota do BFF é simulada no navegador; nada aqui é medição de equipamento real, e o artigo diz isso.
 */
import path from "node:path";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { API_URL, EMAIL, login, PASSWORD } from "./helpers";

const DIR = path.resolve(__dirname, "..", "..", "..", "docs", "help", "assets", "rede", "qualidade-do-servico");
const FIXED = "2026-10-30T15:20:00.000Z";   // horário fixo dos cenários: a captura não depende do relógio
const M = (over: Record<string, unknown>) => ({
  id: "wan.link_status", group: "WAN", status: "valid", value: "Up", unit: null, source: "ACS_CACHE", scope: "WAN_UNCLASSIFIED", instance: null, collected_at: FIXED, freshness_s: 60, ...over,
});
const IND = (over: Record<string, unknown> = {}) => ({
  wan: { state: "ok", metric_ids: [] }, optical: { state: "ok", metric_ids: [] }, wifi: { state: "unknown", metric_ids: [] }, cpe: { state: "ok", metric_ids: [] }, ...over,
});
const CAPS = { modes: { quick: { offered: true, reason: null } } };

async function confirmDemoA2(request: APIRequestContext) {
  const tok = (await (await request.post(`${API_URL}/v1/auth/token`, { data: { email: EMAIL, password: PASSWORD } })).json()).access_token as string;
  const h = { Authorization: `Bearer ${tok}` };
  expect((await request.post(`${API_URL}/v1/onu-cpe-links/suggest`, { headers: h })).status()).toBe(201);
  const links = (await (await request.get(`${API_URL}/v1/onu-cpe-links?status=suggested&limit=200`, { headers: h })).json()) as { id: string; onu: { serial: string } }[];
  const mine = links.find((l) => l.onu.serial === "DEMOA0002");
  if (mine) expect((await request.post(`${API_URL}/v1/onu-cpe-links/${mine.id}/confirm`, { headers: h })).status()).toBe(200);
}

async function openTab(page: Page) {
  await login(page);
  await page.goto("/rede");
  await page.getByTestId("onu-open").filter({ hasText: "DEMOA0002" }).click();
  await page.getByRole("tab", { name: "Qualidade" }).click();
  await page.evaluate(() => document.fonts.ready);
}
const shot = (page: Page, name: string, full = false) => page.screenshot({ path: path.join(DIR, name), fullPage: full, animations: "disabled", mask: [page.getByTestId("freshness"), page.getByTestId("volatile")], maskColor: "#C9D1DA" });

for (const vp of [{ name: "desktop", width: 1440, height: 900 }, { name: "mobile", width: 390, height: 844 }]) {
  test(`rede/qualidade-do-servico (estado real) - ${vp.name}`, async ({ page, request }) => {
    await page.setViewportSize({ width: vp.width, height: vp.height });
    await confirmDemoA2(request);
    await openTab(page);
    await page.getByTestId("quality-run").click();
    await expect(page.getByTestId("quality-global")).toHaveAttribute("data-state", "insufficient_data");
    await page.getByTestId("quality-details").locator("summary").click();
    await shot(page, `${vp.name}.png`, true);
  });
}

test("rede/qualidade-do-servico (cenário) - atenção com hipótese e leitura antiga", async ({ page, request }) => {
  await page.setViewportSize({ width: 1440, height: 1500 });
  await confirmDemoA2(request);
  const run = (id: string, over: Record<string, unknown>) => ({ id, mode: "quick", created_at: FIXED, hypotheses: [], metrics: [], ...over });
  let phase: "attention" | "stale" = "attention";
  await page.route("**/bff/cpes/*/quality", (r) => r.fulfill({
    json: {
      caps: CAPS,
      runs: phase === "attention" ? [run("11111111-1111-4111-8111-111111111111", {
        metrics: [M({ value: "Down" }), M({ id: "optical.rx_dbm", group: "OPTICAL", value: -18.75, unit: "dBm", source: "OLT_ADAPTER", scope: "PON", details: { judged: false } })],
        hypotheses: [{ code: "OPTICAL_ATTENTION", label: "Indícios de problema no enlace óptico; validar a OLT e a conectorização", confidence: "low", recommended_check: "Conferir a leitura na OLT e a conectorização da CTO/ONU", caveats: ["Uma única amostra de RX não prova rompimento"] }],
        summary: { state: "attention", observations: [{ code: "WAN_LINK_DOWN", scope: "WAN_UNCLASSIFIED" }], indicators: IND({ wan: { state: "attention", metric_ids: [] } }), note: null },
      })] : [run("22222222-2222-4222-8222-222222222222", {
        metrics: [M({ status: "stale", freshness_s: 40 * 3600 })],
        summary: { state: "insufficient_data", observations: [], indicators: IND({ wan: { state: "stale", metric_ids: [] }, cpe: { state: "unknown", metric_ids: [] } }), note: "sem evidência suficiente para localizar um gargalo" },
      })],
    },
  }));
  await openTab(page);
  await expect(page.getByTestId("quality-global")).toContainText("Atenção");
  await page.getByTestId("quality-details").locator("summary").click();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.getByTestId("onu-quick").locator("> div").nth(1).screenshot({ path: path.join(DIR, "cenario-atencao.png"), animations: "disabled" });
  phase = "stale";
  await page.reload();
  await page.getByTestId("onu-open").filter({ hasText: "DEMOA0002" }).click();
  await page.getByRole("tab", { name: "Qualidade" }).click();
  await expect(page.getByTestId("quality-ind-wan")).toContainText("Leitura antiga");
  await page.getByTestId("quality-details").locator("summary").click();
  await page.evaluate(() => document.fonts.ready);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.getByTestId("onu-quick").locator("> div").nth(1).screenshot({ path: path.join(DIR, "cenario-leitura-antiga.png"), animations: "disabled" });
});
