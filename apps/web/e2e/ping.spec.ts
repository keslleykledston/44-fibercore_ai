import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { API_URL, EMAIL, login, PASSWORD } from "./helpers";

// Teste de ping TR-143 (ADR-0039), aba "Ping e latência" do Diagnóstico da ONU. O estado "indisponível" do primeiro teste é REAL (a API; o aparelho demo não é de bancada). Os demais estados dependem de
// homologação em equipamento e de um destino de ping no Edge, que não existem aqui: são CENÁRIOS, com a resposta da rota BFF simulada no navegador. Nada aqui é medição de equipamento real.
const row = (page: Page, serial: string) => page.getByTestId("onu-open").filter({ hasText: serial });
const PING_URL = /\/bff\/cpes\/[^/]+\/ping(\?.*)?$/;   // com ou sem `?run=` (a leitura pergunta pelo pedido aceito)
const RUN_ID = "11111111-1111-4111-8111-111111111111";
const RUN = (over: Record<string, unknown> = {}) => ({
  id: RUN_ID, target_id: "core-lab", status: "completed", created_at: new Date().toISOString(), sent: 5, success: 5, failure: 0, loss_pct: 0, avg_ms: 12, min_ms: 11, max_ms: 14, spread_ms: 3, reason: null, ...over,
});
const CAPS = (over: Record<string, unknown> = {}) => ({
  bench_target: true, test: { offered: true, reason: null }, ready: true, shape: { repetitions: 5, timeout_ms: 1000 }, limits: { per_cpe_per_hour: 6 },
  targets: [{ id: "core-lab", label: "Core do laboratório", target_kind: "CORE", region: "LAB", ready: true }], ...over,
});

async function confirmDemoA2(request: APIRequestContext) {
  const tok = (await (await request.post(`${API_URL}/v1/auth/token`, { data: { email: EMAIL, password: PASSWORD } })).json()).access_token as string;
  const h = { Authorization: `Bearer ${tok}` };
  expect((await request.post(`${API_URL}/v1/onu-cpe-links/suggest`, { headers: h })).status()).toBe(201);
  const links = (await (await request.get(`${API_URL}/v1/onu-cpe-links?status=suggested&limit=200`, { headers: h })).json()) as { id: string; onu: { serial: string } }[];
  const mine = links.find((l) => l.onu.serial === "DEMOA0002");
  if (mine) expect((await request.post(`${API_URL}/v1/onu-cpe-links/${mine.id}/confirm`, { headers: h })).status()).toBe(200);
}

async function openPing(page: Page) {
  await page.setViewportSize({ width: 1440, height: 900 });
  await login(page);
  await page.goto("/rede");
  await row(page, "DEMOA0002").click();
  await page.getByTestId("onu-diag-link").click();
  await page.getByTestId("diag-tab-latencia").click();
}

test("ping: no aparelho demo o teste está indisponível, com o motivo, e não há botão de pedir (estado REAL)", async ({ page, request }) => {
  await confirmDemoA2(request);
  await openPing(page);
  const blocked = page.getByTestId("ping-blocked");
  await expect(blocked).toBeVisible();
  await expect(blocked).toHaveAttribute("data-reason", "operation_not_homologated");
  await expect(blocked).toContainText("Teste indisponível neste aparelho");
  await expect(page.getByTestId("ping-start")).toHaveCount(0);
  await expect(page.getByTestId("ping-kpis")).toContainText("—");
  await expect(page.getByTestId("ping-kpis")).not.toContainText("0 ms");
  await expect(page.getByTestId("ping-limits")).toContainText("Jitter e DNS: não disponíveis");
  // contrato do BFF: lista fechada de campos; nada interno da API (cpe_id, job_id, edge_support, certificação...) chega ao navegador
  const tok = (await (await page.request.post(`${API_URL}/v1/auth/token`, { data: { email: EMAIL, password: PASSWORD } })).json()).access_token as string;
  const cpes = (await (await page.request.get(`${API_URL}/v1/cpes`, { headers: { Authorization: `Bearer ${tok}` } })).json()) as { id: string; canonical_serial: string }[];
  const body = await (await page.request.get(`/bff/cpes/${cpes.find((c) => c.canonical_serial === "DEMOA0002")!.id}/ping`)).json();
  expect(Object.keys(body).sort()).toEqual(["caps", "run_seen", "runs"]);
  expect(Object.keys(body.caps).sort()).toEqual(["bench_target", "limits", "ready", "shape", "targets", "test"]);
  expect(Object.keys(body.caps.test).sort()).toEqual(["offered", "reason"]);
  expect(JSON.stringify(body)).not.toMatch(/cpe_id|job_id|edge_support|certification|unsupported/);
  expect((await new AxeBuilder({ page: page as never }).include('[data-testid="ping-section"]').analyze()).violations).toEqual([]);
});

test("ping (cenário): o pedido envia só a chave e o nome lógico do destino e passa a aguardar a aprovação de outra pessoa", async ({ page, request }) => {
  await confirmDemoA2(request);
  let posted: Record<string, unknown> | null = null;
  let runs: unknown[] = [];
  await page.route(PING_URL, (r) => r.fulfill({ json: { caps: CAPS(), runs } }));
  await page.route("**/bff/cpes/*/ping/runs", async (r) => {
    posted = r.request().postDataJSON();
    runs = [RUN({ status: "awaiting_approval", sent: null, success: null, failure: null, loss_pct: null, avg_ms: null, min_ms: null, max_ms: null, spread_ms: null })];
    await r.fulfill({ status: 201, json: { ok: true, outcome: "submitted", run_id: RUN_ID } });
  });
  await openPing(page);
  await expect(page.getByTestId("ping-target")).toHaveValue("core-lab");
  await page.getByTestId("ping-start").click();
  await expect(page.getByTestId("ping-active")).toContainText("Aguardando aprovação de outra pessoa");
  expect(Object.keys(posted ?? {}).sort()).toEqual(["key", "target_id"]);                            // nenhum endereço, nenhum parâmetro do aparelho
  expect((posted as { target_id?: string } | null)?.target_id).toBe("core-lab");
  await expect(page.getByTestId("ping-start")).toBeDisabled();
  await expect(page.getByTestId("ping-pending")).toHaveCount(0);                                     // a leitura já mostra a execução: sem trava de pedido
});

test("ping (cenário): resultado concluído mostra latência e perda; campo sem medição é traço, nunca zero", async ({ page, request }) => {
  await confirmDemoA2(request);
  await page.route(PING_URL, (r) => r.fulfill({ json: { caps: CAPS(), runs: [RUN({ loss_pct: 20, success: 4, failure: 1, avg_ms: 12 })] } }));
  await openPing(page);
  const k = page.getByTestId("ping-kpis");
  await expect(k).toContainText("11 ms");
  await expect(k).toContainText("14 ms");
  await expect(k).toContainText("20 %");
  await expect(page.getByTestId("ping-limits")).toContainText("Amplitude (máx − mín): 3 ms");
  await page.getByTestId("ping-history").locator("summary").click();
  await expect(page.getByTestId("ping-history-row").first()).toContainText("4/5 respostas");
  // inconclusivo: sem números inventados
  await page.unroute(PING_URL);
  await page.route(PING_URL, (r) => r.fulfill({ json: { caps: CAPS(), runs: [RUN({ status: "inconclusive", loss_pct: null, avg_ms: null, min_ms: null, max_ms: null, spread_ms: null, sent: null, success: null, failure: null, reason: "no_times" })] } }));
  await page.reload();
  await expect(page.getByTestId("ping-kpis")).not.toContainText(" ms");
  await expect(page.getByTestId("ping-kpis")).not.toContainText("0 %");
  await page.getByTestId("ping-history").locator("summary").click();
  await expect(page.getByTestId("ping-history-row").first()).toContainText("não informou os tempos de resposta");
});

test("ping (cenário): resposta 502 ao pedido é AMBÍGUA: trava, e Confirmar pedido repete a MESMA chave e o MESMO destino", async ({ page, request }) => {
  await confirmDemoA2(request);
  const bodies: { key: string; target_id: string }[] = [];
  let runs: unknown[] = [];
  await page.route(PING_URL, (r) => r.fulfill({ json: { caps: CAPS(), runs } }));
  await page.route("**/bff/cpes/*/ping/runs", async (r) => {
    bodies.push(r.request().postDataJSON());
    if (bodies.length === 1) return r.fulfill({ status: 502, json: { error: "failed" } });            // a primeira resposta se perde: o pedido pode ter chegado
    runs = [RUN({ status: "awaiting_approval" })];
    return r.fulfill({ status: 201, json: { ok: true, outcome: "submitted", run_id: RUN_ID } });
  });
  await openPing(page);
  await page.getByTestId("ping-start").click();
  await expect(page.getByTestId("ping-pending")).toContainText("a confirmação não chegou");
  await expect(page.getByTestId("ping-start")).toBeDisabled();                                       // travado: nada de segundo clique
  await page.getByTestId("ping-pending-confirm").click();
  await expect(page.getByTestId("ping-active")).toContainText("Aguardando aprovação");
  expect(bodies.length).toBe(2);
  expect(bodies[1]).toEqual(bodies[0]);                                                              // a MESMA chave de idempotência e o MESMO destino
});

test("ping (cenário): pedido aceito só destrava quando uma leitura mostra ESSA execução (nunca pelo relógio)", async ({ page, request }) => {
  await confirmDemoA2(request);
  let mode: "none" | "other" | "seen" = "none";
  await page.route(PING_URL, (r) => r.fulfill({ json: {
    caps: CAPS(), runs: mode === "other" ? [RUN({ id: "33333333-3333-4333-8333-333333333333" })] : [],
    ...(r.request().url().includes("run=") ? { run_seen: mode === "seen" } : {}),
  } }));
  await page.route("**/bff/cpes/*/ping/runs", (r) => r.fulfill({ status: 201, json: { ok: true, outcome: "submitted", run_id: RUN_ID } }));
  await openPing(page);
  await page.clock.install();
  await page.getByTestId("ping-start").click();
  await expect(page.getByTestId("ping-pending")).toContainText("Aguardando a leitura mostrar a execução");
  await page.clock.fastForward("21:00");                                                             // passa qualquer prazo: o relógio não prova nada
  await expect(page.getByTestId("ping-pending")).toBeVisible();
  await expect(page.getByTestId("ping-start")).toBeDisabled();
  mode = "other";                                                                                    // a execução de OUTRA pessoa aparece: não prova nada
  await page.getByTestId("ping-pending-refresh").click();
  await expect(page.getByTestId("ping-pending")).toBeVisible();
  await expect(page.getByTestId("ping-start")).toBeDisabled();
  mode = "seen";                                                                                     // o BFF confirma pelo id que a execução existe
  await page.getByTestId("ping-pending-refresh").click();
  await expect(page.getByTestId("ping-pending")).toHaveCount(0);
  await expect(page.getByTestId("ping-start")).toBeEnabled();
});

test("ping (cenário): recusa definitiva (409) mostra o motivo em palavras e não trava; falha de carga tem nova tentativa", async ({ page, request }) => {
  await confirmDemoA2(request);
  let reads = 0;
  await page.route(PING_URL, (r) => { reads += 1; return reads === 1 ? r.fulfill({ status: 502, json: { error: "failed" } }) : r.fulfill({ json: { caps: CAPS(), runs: [] } }); });
  await page.route("**/bff/cpes/*/ping/runs", (r) => r.fulfill({ status: 409, json: { error: "blocked", reason: "cpe_busy" } }));
  await openPing(page);
  await expect(page.getByTestId("ping-error")).toContainText("Não foi possível carregar o teste de ping");
  await page.getByRole("button", { name: "Tentar novamente" }).click();
  await page.getByTestId("ping-start").click();
  await expect(page.getByTestId("ping-refusal")).toContainText("Já existe um teste em andamento neste aparelho");
  await expect(page.getByTestId("ping-pending")).toHaveCount(0);
  await expect(page.getByTestId("ping-start")).toBeEnabled();                                        // nada foi criado: a trava saiu
});
