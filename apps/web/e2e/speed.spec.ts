import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { API_URL, EMAIL, login, PASSWORD } from "./helpers";

// Teste de banda TR-143 (ADR-0038), aba "Teste de banda" do painel da ONU. O estado "indisponível" abaixo é REAL (a API, o aparelho demo não é de bancada). Os demais estados dependem de
// homologação em equipamento e de um nó de teste, que não existem aqui: são CENÁRIOS, com a resposta da rota BFF simulada no navegador (rotulados assim nas capturas da ajuda).
const row = (page: Page, serial: string) => page.getByTestId("onu-open").filter({ hasText: serial });
const CPE = "00000000-0000-4000-8000-000000000001";
const RUN = (over: Record<string, unknown>) => ({
  id: "11111111-1111-4111-8111-111111111111", group_id: "22222222-2222-4222-8222-222222222222", direction: "download", endpoint_id: "core-sp-1", profile: "10mb", status: "completed",
  created_at: new Date().toISOString(), mbps: null, bytes: null, duration_ms: null, reliable: false, reason: null, basis: null, ...over,
});
const CAPS = (over: Record<string, unknown> = {}) => ({
  bench_target: true, ready: true, profiles: ["10mb", "50mb", "200mb"], redirect_verified: true,
  directions: { download: { operation: "speed_test_download", offered: true, reason: null }, upload: { operation: "speed_test_upload", offered: true, reason: null } },
  endpoints: [{ id: "core-sp-1", label: "Nó Core São Paulo", target_kind: "CORE", region: "DC-1", ready: true, enabled: true, health: "ok" }], ...over,
});

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
  await page.getByRole("tab", { name: "Teste de banda" }).click();
}

test("teste de banda: no aparelho demo o teste está indisponível, com o motivo, e não há botão de iniciar (estado REAL)", async ({ page, request }) => {
  await confirmDemoA2(request);
  await openTab(page);
  const blocked = page.getByTestId("speed-blocked");
  await expect(blocked).toBeVisible();
  await expect(blocked).toHaveAttribute("data-reason", "operation_not_homologated");
  await expect(blocked).toContainText("Teste indisponível neste aparelho");
  await expect(blocked).toContainText("ainda não foi homologado");
  await expect(page.getByTestId("speed-start-download")).toHaveCount(0);
  await expect(page.getByTestId("speed-kpi-download")).toContainText("—");              // sem teste: traço, nunca 0
  await expect(page.getByTestId("speed-kpi-download")).not.toContainText("0 Mbps");
  await expect(page.getByText("Mede a WAN da ONT, não o Wi‑Fi nem a rede interna")).toBeVisible();
  expect((await new AxeBuilder({ page: page as never }).include('[data-testid="speed-section"]').analyze()).violations).toEqual([]);
});

test("teste de banda (cenário): pedir o download envia só nomes lógicos e passa a aguardar a aprovação de outra pessoa", async ({ page, request }) => {
  await confirmDemoA2(request);
  let posted: Record<string, unknown> | null = null;
  let runs: unknown[] = [];
  await page.route("**/bff/cpes/*/speed", (r) => r.fulfill({ json: { caps: CAPS(), runs } }));
  await page.route("**/bff/cpes/*/speed/runs", async (r) => {
    posted = r.request().postDataJSON();
    runs = [RUN({ status: "awaiting_approval" })];
    await r.fulfill({ status: 201, json: { ok: true, outcome: "submitted" } });
  });
  await openTab(page);
  await expect(page.getByTestId("speed-target")).toContainText("Core");
  await expect(page.getByRole("radio", { name: /Internet/ })).toBeDisabled();             // sem destino pronto na Internet
  await page.getByLabel("Tamanho do arquivo").selectOption("50mb");
  await page.getByTestId("speed-start-download").click();
  await expect(page.getByTestId("speed-active")).toContainText("Aguardando aprovação de outra pessoa");
  expect(posted).toMatchObject({ direction: "download", endpoint_id: "core-sp-1", profile: "50mb" });
  expect(JSON.stringify(posted)).not.toMatch(/http|url|:\/\//i);                          // nenhum endereço sai do navegador
  await expect(page.getByTestId("speed-start-download")).toBeDisabled();                  // um teste por vez
  await expect(page.getByTestId("speed-start-upload")).toBeDisabled();
  expect((await new AxeBuilder({ page: page as never }).include('[data-testid="speed-section"]').analyze()).violations).toEqual([]);
});

test("teste de banda (cenário): resultado confiável, parcial e erro do aparelho aparecem sem inventar número", async ({ page, request }) => {
  await confirmDemoA2(request);
  const runs = [
    RUN({ id: "33333333-3333-4333-8333-333333333333", direction: "upload", status: "partial", mbps: 40, bytes: 10_000_000, duration_ms: 2000, reason: "too_short" }),
    RUN({ status: "completed", mbps: 94.25, reliable: true, bytes: 10_000_000, duration_ms: 8000, basis: "test_bytes_received" }),
    RUN({ id: "44444444-4444-4444-8444-444444444444", status: "error", reason: "device_error" }),
  ];
  await page.route("**/bff/cpes/*/speed", (r) => r.fulfill({ json: { caps: CAPS(), runs } }));
  await openTab(page);
  await expect(page.getByTestId("speed-kpi-upload")).toContainText("40 Mbps");
  await expect(page.getByTestId("speed-kpi-upload")).toContainText("Parcial");
  await expect(page.getByTestId("speed-kpi-download")).toContainText("94,25 Mbps");        // o último download (o mais recente com número é o concluído? não: o mais recente da lista)
  await page.getByTestId("speed-history").locator("summary").click();
  const rows = page.getByTestId("speed-history-row");
  await expect(rows).toHaveCount(3);
  await expect(rows.nth(0)).toContainText("Medição curta demais");
  await expect(rows.nth(2)).toContainText("Erro no aparelho");
  await expect(rows.nth(2)).not.toContainText("Mbps");
  await expect(rows.nth(2)).toContainText("O aparelho informou erro");
});

test("teste de banda (cenário): a recusa da API aparece em palavras e nada fica em andamento", async ({ page, request }) => {
  await confirmDemoA2(request);
  await page.route("**/bff/cpes/*/speed", (r) => r.fulfill({ json: { caps: CAPS(), runs: [] } }));
  await page.route("**/bff/cpes/*/speed/runs", (r) => r.fulfill({ status: 409, json: { error: "blocked", reason: "pon_busy" } }));
  await openTab(page);
  await page.getByTestId("speed-start-upload").click();
  await expect(page.getByTestId("speed-refusal")).toContainText("Já existe um teste em andamento nesta PON");
  await expect(page.getByTestId("speed-active")).toHaveCount(0);
});

test("teste de banda (cenário): sem destino pronto não há botão, e a falha de carga tem nova tentativa", async ({ page, request }) => {
  await confirmDemoA2(request);
  let n = 0;
  await page.route("**/bff/cpes/*/speed", (r) => {
    n += 1;
    return n === 1 ? r.fulfill({ status: 502, json: { error: "failed" } }) : r.fulfill({ json: { caps: CAPS({ ready: false, endpoints: [{ id: "core-sp-1", label: "Nó", target_kind: "CORE", region: "DC-1", ready: false }] }), runs: [] } });
  });
  await openTab(page);
  await expect(page.getByTestId("speed-error")).toContainText("Não foi possível carregar o teste de banda");
  await page.getByRole("button", { name: "Tentar novamente" }).click();
  await expect(page.getByTestId("speed-not-ready")).toContainText("Nenhum destino respondeu à última verificação do Edge");
  await expect(page.getByTestId("speed-start-download")).toHaveCount(0);
});


test("ONU 360°: o cartão Teste de banda existe com roteador vinculado e a flag ligada, e mostra o mesmo estado real", async ({ page, request }) => {
  await confirmDemoA2(request);
  await page.setViewportSize({ width: 1440, height: 900 });
  await login(page);
  await page.goto("/rede");
  await row(page, "DEMOA0002").click();
  await page.getByTestId("onu-360-link").click();
  const card = page.getByTestId("onu360-speed");
  await expect(card).toContainText("Teste de banda");
  await expect(card.getByTestId("speed-blocked")).toContainText("Teste indisponível neste aparelho");
  await expect(card.getByTestId("speed-start-download")).toHaveCount(0);
});

test("teste de banda (cenário): uma leitura lenta e antiga nunca sobrescreve o estado mais recente", async ({ page, request }) => {
  test.setTimeout(90_000);
  await confirmDemoA2(request);
  let n = 0;
  const done = RUN({ status: "completed", mbps: 93.7, reliable: true, bytes: 10_000_000, duration_ms: 8000 });
  await page.route("**/bff/cpes/*/speed", async (r) => {
    n += 1;
    const mine = n;
    if (mine === 1) return r.fulfill({ json: { caps: CAPS(), runs: [] } });                                         // abrir a aba
    if (mine === 2) return r.fulfill({ json: { caps: CAPS(), runs: [RUN({ status: "awaiting_approval" })] } });      // logo depois do pedido
    if (mine === 3) { await new Promise((res) => setTimeout(res, 6500)); return r.fulfill({ json: { caps: CAPS(), runs: [] } }); }   // leitura LENTA e antiga: "sem teste ativo"
    return r.fulfill({ json: { caps: CAPS(), runs: [done] } });                                                      // a seguinte, mais nova, já com o resultado
  });
  await page.route("**/bff/cpes/*/speed/runs", (r) => r.fulfill({ status: 201, json: { ok: true, outcome: "submitted" } }));
  await openTab(page);
  await page.getByTestId("speed-start-download").click();
  await expect(page.getByTestId("speed-active")).toBeVisible();
  await expect(page.getByTestId("speed-kpi-download")).toContainText("93,7 Mbps", { timeout: 15_000 });
  await page.waitForTimeout(4000);                                                                                   // a resposta antiga chega agora
  await expect(page.getByTestId("speed-kpi-download")).toContainText("93,7 Mbps");
  await expect(page.getByTestId("speed-active")).toHaveCount(0);
});

test("teste de banda (cenário): pedido aceito continua em curso se a leitura seguinte falha ou chega velha, e os botões ficam travados", async ({ page, request }) => {
  test.setTimeout(90_000);
  await confirmDemoA2(request);
  let reads = 0, posts = 0;
  await page.route("**/bff/cpes/*/speed", (r) => {
    reads += 1;
    if (reads === 1) return r.fulfill({ json: { caps: CAPS(), runs: [] } });                                          // abrir a aba
    if (reads === 2) return r.fulfill({ status: 502, json: { error: "failed" } });                                    // a leitura logo após o pedido FALHA
    if (reads === 3) return r.fulfill({ json: { caps: CAPS(), runs: [] } });                                          // a seguinte chega VELHA (ainda sem a execução)
    return r.fulfill({ json: { caps: CAPS(), runs: [RUN({ status: "awaiting_approval" })] } });                      // por fim a execução aparece
  });
  await page.route("**/bff/cpes/*/speed/runs", (r) => { posts += 1; return r.fulfill({ status: 201, json: { ok: true, outcome: "submitted" } }); });
  await openTab(page);
  await page.getByTestId("speed-start-download").click();
  await expect(page.getByTestId("speed-pending")).toBeVisible();
  await expect(page.getByTestId("speed-refresh-failed")).toBeVisible();                                                 // avisa, não troca a tela por um erro
  await expect(page.getByTestId("speed-error")).toHaveCount(0);
  await expect(page.getByTestId("speed-start-download")).toBeDisabled();
  await expect(page.getByTestId("speed-start-upload")).toBeDisabled();
  await page.waitForTimeout(4800);                                                                                       // a leitura velha já chegou: continua travado
  await expect(page.getByTestId("speed-start-download")).toBeDisabled();
  await expect(page.getByTestId("speed-pending")).toBeVisible();
  await expect(page.getByTestId("speed-active")).toContainText("Aguardando aprovação", { timeout: 15_000 });           // a execução apareceu: o pedido deixa de ser "pendente"
  await expect(page.getByTestId("speed-pending")).toHaveCount(0);
  await expect(page.getByTestId("speed-refresh-failed")).toHaveCount(0);
  expect(posts).toBe(1);                                                                                                 // um único pedido, nunca repetido
});

// Prova do recuo (só roda com a flag desligada no provedor: SPEED_FLAG_OFF=1): a aba, o cartão e a rota do BFF não existem para a tela; o resto do painel segue igual.
test("flag speed_diagnostics desligada: sem aba, sem cartão na ONU 360° e o BFF responde que está desligado", async ({ page, request }) => {
  test.skip(!process.env.SPEED_FLAG_OFF, "rodar com SPEED_FLAG_OFF=1 e a flag desligada no provedor");
  await confirmDemoA2(request);
  await page.setViewportSize({ width: 1440, height: 900 });
  await login(page);
  await page.goto("/rede");
  await row(page, "DEMOA0002").click();
  await expect(page.getByRole("tab", { name: "Histórico" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Teste de banda" })).toHaveCount(0);
  await page.getByTestId("onu-360-link").click();
  await expect(page.getByTestId("onu360-ready")).toBeVisible();
  await expect(page.getByTestId("onu360-speed")).toHaveCount(0);
  const r = await page.request.get(`/bff/cpes/${CPE}/speed`);
  expect([403, 404]).toContain(r.status());
});

test("teste de banda (cenário): pedido aceito que a leitura não mostra NUNCA destrava pelo relógio; só uma leitura que mostre a execução", async ({ page, request }) => {
  await confirmDemoA2(request);
  let showRun = false;
  await page.route("**/bff/cpes/*/speed", (r) => r.fulfill({ json: { caps: CAPS(), runs: showRun ? [RUN({ status: "awaiting_approval" })] : [] } }));
  let posts = 0;
  await page.route("**/bff/cpes/*/speed/runs", (r) => { posts += 1; return r.fulfill({ status: 201, json: { ok: true, outcome: "submitted" } }); });
  await openTab(page);
  await page.clock.install();
  await page.getByTestId("speed-start-download").click();
  await expect(page.getByTestId("speed-pending")).toBeVisible();
  await page.clock.fastForward("21:00");                                                                               // passa o prazo de vida do pedido (e do que o relógio local sabe)
  await expect(page.getByTestId("speed-pending")).toContainText("a leitura ainda não mostra a execução");
  await expect(page.getByTestId("speed-start-download")).toBeDisabled();
  await expect(page.getByTestId("speed-start-upload")).toBeDisabled();
  showRun = true;
  await page.getByTestId("speed-pending-refresh").click();
  await expect(page.getByTestId("speed-active")).toContainText("Aguardando aprovação");
  await expect(page.getByTestId("speed-pending")).toHaveCount(0);
  expect(posts).toBe(1);
});

test("teste de banda (cenário): sessão expirada durante o acompanhamento para de consultar e oferece entrar de novo", async ({ page, request }) => {
  test.setTimeout(60_000);
  await confirmDemoA2(request);
  let reads = 0;
  await page.route("**/bff/cpes/*/speed", (r) => {
    reads += 1;
    return reads <= 2 ? r.fulfill({ json: { caps: CAPS(), runs: [] } }) : r.fulfill({ status: 401, json: { error: "session" } });
  });
  await page.route("**/bff/cpes/*/speed/runs", (r) => r.fulfill({ status: 201, json: { ok: true, outcome: "submitted" } }));
  await openTab(page);
  await page.getByTestId("speed-start-download").click();                                                                // a leitura seguinte (a 2ª, logo após o pedido, ainda vem vazia; a 3ª, do acompanhamento, responde 401)
  await expect(page.getByTestId("speed-error")).toContainText("Sua sessão expirou", { timeout: 15_000 });
  await expect(page.getByRole("link", { name: "Entrar de novo" })).toHaveAttribute("href", "/login");
  await expect(page.getByTestId("speed-start-download")).toHaveCount(0);
  const seen = reads;
  await page.waitForTimeout(5000);                                                                                       // mais de um ciclo de acompanhamento
  expect(reads).toBe(seen);                                                                                              // parou de consultar
});

test("teste de banda (cenário): resposta 502 ao pedido é ambígua, trava os botões e só destrava por uma leitura feita depois do prazo sem execução nova", async ({ page, request }) => {
  await confirmDemoA2(request);
  let posts = 0;
  await page.route("**/bff/cpes/*/speed", (r) => r.fulfill({ json: { caps: CAPS(), runs: [] } }));
  await page.route("**/bff/cpes/*/speed/runs", (r) => { posts += 1; return r.fulfill({ status: 502, json: { error: "failed" } }); });
  await openTab(page);
  await page.clock.install();
  await page.getByTestId("speed-start-download").click();
  await expect(page.getByTestId("speed-refusal")).toContainText("Não foi possível confirmar o pedido");
  await expect(page.getByTestId("speed-pending")).toBeVisible();
  await expect(page.getByTestId("speed-start-download")).toBeDisabled();
  await expect(page.getByTestId("speed-start-upload")).toBeDisabled();
  await page.getByTestId("speed-pending-refresh").click();                                                              // uma leitura ANTES do prazo não basta
  await expect(page.getByTestId("speed-start-download")).toBeDisabled();
  await page.clock.fastForward("01:05");                                                                                // passa o prazo; a leitura periódica seguinte começa DEPOIS dele, sem execução nova: destrava sozinha
  await expect(page.getByTestId("speed-start-download")).toBeEnabled();
  await expect(page.getByTestId("speed-pending")).toHaveCount(0);
  expect(posts).toBe(1);
});

test("teste de banda (cenário): recusa definitiva (409) não trava e a próxima tentativa é possível", async ({ page, request }) => {
  await confirmDemoA2(request);
  await page.route("**/bff/cpes/*/speed", (r) => r.fulfill({ json: { caps: CAPS(), runs: [] } }));
  await page.route("**/bff/cpes/*/speed/runs", (r) => r.fulfill({ status: 409, json: { error: "blocked", reason: "tenant_busy" } }));
  await openTab(page);
  await page.getByTestId("speed-start-download").click();
  await expect(page.getByTestId("speed-refusal")).toContainText("limite de testes simultâneos");
  await expect(page.getByTestId("speed-pending")).toHaveCount(0);
  await expect(page.getByTestId("speed-start-download")).toBeEnabled();
});
