/**
 * Capturas da ajuda "Como testar a banda de uma ONT" (ADR-0038). Gera docs/help/assets/rede/testar-banda/*.png.
 * - desktop.png / mobile.png: estado REAL da aplicação integrada com seed sintético (teste indisponível: o aparelho demo não é de bancada).
 * - cenario-*.png: CENÁRIOS DE TESTE. A rota do BFF é simulada no navegador (não existe homologação em equipamento nem nó de teste); o artigo diz isso. Nada aqui é medição real.
 */
import path from "node:path";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { API_URL, EMAIL, login, PASSWORD } from "./helpers";

const DIR = path.resolve(__dirname, "..", "..", "..", "docs", "help", "assets", "rede", "testar-banda");
const FIXED = "2026-10-30T15:20:00.000Z";   // horário fixo dos cenários: a captura não depende do relógio
const RUN = (over: Record<string, unknown>) => ({
  id: "11111111-1111-4111-8111-111111111111", group_id: "22222222-2222-4222-8222-222222222222", direction: "download", endpoint_id: "core-sp-1", profile: "50mb", status: "completed",
  created_at: FIXED, mbps: null, bytes: null, duration_ms: null, reliable: false, reason: null, basis: null, ...over,
});
const CAPS = {
  bench_target: true, ready: true, profiles: ["10mb", "50mb", "200mb"], redirect_verified: true,
  directions: { download: { offered: true, reason: null }, upload: { offered: true, reason: null } },
  endpoints: [{ id: "core-sp-1", label: "Nó de teste Core", target_kind: "CORE", region: "DC-1", ready: true }],
};

async function confirmDemoA2(request: APIRequestContext) {
  const tok = (await (await request.post(`${API_URL}/v1/auth/token`, { data: { email: EMAIL, password: PASSWORD } })).json()).access_token as string;
  const h = { Authorization: `Bearer ${tok}` };
  expect((await request.post(`${API_URL}/v1/onu-cpe-links/suggest`, { headers: h })).status()).toBe(201);
  const links = (await (await request.get(`${API_URL}/v1/onu-cpe-links?status=suggested&limit=200`, { headers: h })).json()) as { id: string; onu: { serial: string } }[];
  const mine = links.find((l) => l.onu.serial === "DEMOA0002");
  if (mine) expect((await request.post(`${API_URL}/v1/onu-cpe-links/${mine.id}/confirm`, { headers: h })).status()).toBe(200);
}

async function openBanda(page: Page) {
  await login(page);
  await page.goto("/rede");
  await page.getByTestId("onu-open").filter({ hasText: "DEMOA0002" }).click();
  await page.getByRole("tab", { name: "Teste de banda" }).click();
  await page.evaluate(() => document.fonts.ready);
}
const shot = (page: Page, name: string, full = false) => page.screenshot({ path: path.join(DIR, name), fullPage: full, animations: "disabled", mask: [page.getByTestId("freshness"), page.getByTestId("volatile")], maskColor: "#C9D1DA" });

for (const vp of [{ name: "desktop", width: 1440, height: 900 }, { name: "mobile", width: 390, height: 844 }]) {
  test(`rede/testar-banda (estado real) - ${vp.name}`, async ({ page, request }) => {
    await page.setViewportSize({ width: vp.width, height: vp.height });
    await confirmDemoA2(request);
    await openBanda(page);
    await expect(page.getByTestId("speed-blocked")).toBeVisible();
    await shot(page, `${vp.name}.png`, true);
  });
}

test("rede/testar-banda (cenário) - aguardando aprovação e resultado", async ({ page, request }) => {
  await page.setViewportSize({ width: 1440, height: 1500 });   // alto o bastante para o painel mostrar o histórico inteiro
  await confirmDemoA2(request);
  let phase: "waiting" | "done" = "waiting";
  await page.route("**/bff/cpes/*/speed", (r) => r.fulfill({
    json: {
      caps: CAPS,
      runs: phase === "waiting" ? [RUN({ status: "awaiting_approval" })] : [
        RUN({ id: "33333333-3333-4333-8333-333333333333", direction: "upload", status: "partial", mbps: 38.4, bytes: 50_000_000, duration_ms: 2600, reason: "too_short" }),
        RUN({ status: "completed", mbps: 93.7, reliable: true, bytes: 50_000_000, duration_ms: 4270, basis: "test_bytes_received" }),
        RUN({ id: "44444444-4444-4444-8444-444444444444", status: "error", reason: "device_error", created_at: "2026-10-30T14:05:00.000Z" }),
      ],
    },
  }));
  await openBanda(page);
  await expect(page.getByTestId("speed-active")).toContainText("Aguardando aprovação");
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.getByTestId("onu-quick").locator("> div").nth(1).screenshot({ path: path.join(DIR, "cenario-aguardando.png"), animations: "disabled" });
  phase = "done";
  await page.reload();
  await page.getByTestId("onu-open").filter({ hasText: "DEMOA0002" }).click();
  await page.getByRole("tab", { name: "Teste de banda" }).click();
  await expect(page.getByTestId("speed-kpi-download")).toContainText("93,7 Mbps");
  await page.getByTestId("speed-history").locator("summary").click();
  await page.evaluate(() => document.fonts.ready);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.getByTestId("onu-quick").locator("> div").nth(1).screenshot({ path: path.join(DIR, "cenario-resultado.png"), animations: "disabled" });
});
