import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { API_URL, EMAIL, login, PASSWORD } from "./helpers";

// Diagnóstico de qualidade (QoS-001, ADR-0039), aba "Qualidade" do painel da ONU. O primeiro teste é REAL (API + banco sintético: o aparelho demo não tem leitura do ACS, então a leitura mostra
// "sem leitura", nunca zero). Os cenários simulam a resposta da rota BFF no navegador (rotulados assim nas capturas da ajuda); nada aqui é medição de equipamento real.
const row = (page: Page, serial: string) => page.getByTestId("onu-open").filter({ hasText: serial });
const ID = "11111111-1111-4111-8111-111111111111";
const M = (over: Record<string, unknown>) => ({
  id: "wan.link_status", group: "WAN", status: "valid", value: "Up", unit: null, source: "ACS_CACHE", scope: "WAN_UNCLASSIFIED", instance: null,
  collected_at: new Date().toISOString(), freshness_s: 30, ...over,
});
const IND = (over: Record<string, unknown> = {}) => ({
  wan: { state: "ok", metric_ids: ["wan.link_status"] }, optical: { state: "ok", metric_ids: ["optical.rx_dbm"] }, wifi: { state: "unknown", metric_ids: [] },
  cpe: { state: "ok", metric_ids: ["cpe.uptime_s"] }, ...over,
});
const RUN = (over: Record<string, unknown> = {}) => ({
  id: ID, mode: "quick", created_at: new Date().toISOString(), metrics: [M({}), M({ id: "cpe.uptime_s", group: "CPE", value: 86400, unit: "s", scope: "CPE" })], hypotheses: [],
  summary: { state: "no_anomalies_observed", observations: [], indicators: IND(), note: null }, ...over,
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
  await page.setViewportSize({ width: 1440, height: 900 });
  await login(page);
  await page.goto("/rede");
  await row(page, "DEMOA0002").click();
  await page.getByRole("tab", { name: "Qualidade" }).click();
}

test("qualidade: leitura REAL no aparelho demo mostra 'sem leitura' e dados insuficientes, nunca zero nem OK", async ({ page, request }) => {
  await confirmDemoA2(request);
  await openTab(page);
  await page.getByTestId("quality-run").click();
  const g = page.getByTestId("quality-global");
  await expect(g).toBeVisible();
  await expect(g).toHaveAttribute("data-state", "insufficient_data");
  await expect(g).toContainText("Dados insuficientes para avaliar");
  await expect(page.getByTestId("quality-ind-wifi")).toContainText("Sem leitura");
  await expect(page.getByTestId("quality-ind-optical")).toContainText("sem faixa de referência");   // nível óptico atual, mas sem perfil homologado: não é "ok"
  await expect(page.getByTestId("quality-section")).not.toContainText("Tudo OK");
  await page.getByTestId("quality-details").locator("summary").click();
  await expect(page.getByTestId("quality-metric").first()).toBeVisible();
  expect((await new AxeBuilder({ page: page as never }).include('[data-testid="quality-section"]').analyze()).violations).toEqual([]);
});

test("qualidade (cenário): anomalia observada e hipótese aparecem com ressalva e verificação recomendada", async ({ page, request }) => {
  await confirmDemoA2(request);
  await page.route("**/bff/cpes/*/quality", (r) => r.fulfill({
    json: {
      caps: CAPS,
      runs: [RUN({
        metrics: [M({ value: "Down" }), M({ id: "optical.rx_dbm", group: "OPTICAL", value: -18.75, unit: "dBm", source: "OLT_ADAPTER", scope: "PON" })],
        hypotheses: [{ code: "OPTICAL_ATTENTION", label: "Indícios de problema no enlace óptico; validar a OLT e a conectorização", confidence: "low", evidence_metric_ids: ["optical.rx_dbm"], recommended_check: "Conferir a leitura na OLT", caveats: ["Uma única amostra de RX não prova rompimento"] }],
        summary: { state: "attention", observations: [{ code: "WAN_LINK_DOWN", scope: "WAN_UNCLASSIFIED" }], indicators: IND({ wan: { state: "attention", metric_ids: ["wan.link_status"] } }), note: null },
      })],
    },
  }));
  await openTab(page);
  await expect(page.getByTestId("quality-global")).toContainText("Atenção");
  await expect(page.getByTestId("quality-ind-wan")).toHaveAttribute("data-state", "attention");
  await expect(page.getByTestId("quality-observations")).toContainText("enlace da WAN");
  const h = page.getByTestId("quality-hypothesis");
  await expect(h).toContainText("Indícios de problema no enlace óptico");
  await expect(h).toContainText("Ressalva: Uma única amostra de RX não prova rompimento");
  await expect(h).toContainText("Verificar: Conferir a leitura na OLT");
  await expect(page.getByTestId("quality-hypotheses")).toContainText("não são diagnóstico");
});

test("qualidade (cenário): leitura antiga é marcada como antiga e não vira 'sem anomalia'", async ({ page, request }) => {
  await confirmDemoA2(request);
  const old = 40 * 3600;
  await page.route("**/bff/cpes/*/quality", (r) => r.fulfill({
    json: { caps: CAPS, runs: [RUN({ metrics: [M({ status: "stale", freshness_s: old })], summary: { state: "insufficient_data", observations: [], indicators: IND({ wan: { state: "stale", metric_ids: ["wan.link_status"] } }), note: "sem evidência suficiente para localizar um gargalo" } })] },
  }));
  await openTab(page);
  await expect(page.getByTestId("quality-ind-wan")).toContainText("Leitura antiga");
  await page.getByTestId("quality-details").locator("summary").click();
  await expect(page.getByTestId("quality-metric").first()).toContainText("Leitura antiga");
  await expect(page.getByTestId("quality-metric").first()).toContainText("há 40 h");
});

test("qualidade (cenário): sem permissão para ler, o botão fica desabilitado com o motivo; recusa da API vira texto", async ({ page, request }) => {
  await confirmDemoA2(request);
  await page.route("**/bff/cpes/*/quality", (r) => r.fulfill({ json: { caps: { modes: { quick: { offered: false, reason: "not_permitted" } } }, runs: [] } }));
  await openTab(page);
  await expect(page.getByTestId("quality-run")).toBeDisabled();
  await expect(page.getByTestId("quality-not-offered")).toContainText("não permite");
});

test("qualidade: o pedido envia só a chave de idempotência (nenhum endereço, nenhum parâmetro do aparelho)", async ({ page, request }) => {
  await confirmDemoA2(request);
  let posted: Record<string, unknown> | null = null;
  await page.route("**/bff/cpes/*/quality/runs", async (r) => { posted = r.request().postDataJSON(); await r.continue(); });
  await openTab(page);
  await page.getByTestId("quality-run").click();
  await expect(page.getByTestId("quality-global")).toBeVisible();
  expect(Object.keys(posted ?? {})).toEqual(["key"]);
});

test("flag quality_diagnostics desligada: sem aba, sem cartão na ONU 360° e o BFF responde que está desligado", async ({ page, request }) => {
  test.skip(!process.env.QUALITY_FLAG_OFF, "rodar com QUALITY_FLAG_OFF=1 e a flag desligada no provedor");
  await confirmDemoA2(request);
  await page.setViewportSize({ width: 1440, height: 900 });
  await login(page);
  await page.goto("/rede");
  await row(page, "DEMOA0002").click();
  await expect(page.getByRole("tab", { name: "Histórico" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Qualidade" })).toHaveCount(0);
  await page.getByTestId("onu-360-link").click();
  await expect(page.getByTestId("onu360-ready")).toBeVisible();
  await expect(page.getByTestId("onu360-quality")).toHaveCount(0);
  const r = await page.request.get(`/bff/cpes/00000000-0000-4000-8000-000000000001/quality`);
  expect([403, 404]).toContain(r.status());
});

test("qualidade (cenário): sem nenhuma leitura feita, a tela diz isso e não inventa estado", async ({ page, request }) => {
  await confirmDemoA2(request);
  await page.route("**/bff/cpes/*/quality", (r) => r.fulfill({ json: { caps: CAPS, runs: [] } }));
  await openTab(page);
  await expect(page.getByTestId("quality-empty")).toContainText("Nenhuma leitura feita ainda");
  await expect(page.getByTestId("quality-global")).toHaveCount(0);
  await expect(page.getByTestId("quality-run")).toBeEnabled();
});
