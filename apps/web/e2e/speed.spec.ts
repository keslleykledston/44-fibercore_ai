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
    await r.fulfill({ status: 201, json: { ok: true, outcome: "submitted", run_id: RUN({}).id } });
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
  await page.route("**/bff/cpes/*/speed/runs", (r) => r.fulfill({ status: 201, json: { ok: true, outcome: "submitted", run_id: RUN({}).id } }));
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
  await page.route("**/bff/cpes/*/speed/runs", (r) => { posts += 1; return r.fulfill({ status: 201, json: { ok: true, outcome: "submitted", run_id: RUN({}).id } }); });
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

test("teste de banda (cenário): pedido aceito que a leitura não mostra NUNCA destrava pelo relógio; só uma leitura que mostre ESSA execução", async ({ page, request }) => {
  await confirmDemoA2(request);
  let mode: "none" | "other" | "mine" = "none";
  await page.route("**/bff/cpes/*/speed", (r) => r.fulfill({ json: { caps: CAPS(), runs: mode === "none" ? [] : mode === "other" ? [RUN({ id: "33333333-3333-4333-8333-333333333333", status: "completed", mbps: 50, reliable: true })] : [RUN({ status: "awaiting_approval" })] } }));
  let posts = 0;
  await page.route("**/bff/cpes/*/speed/runs", (r) => { posts += 1; return r.fulfill({ status: 201, json: { ok: true, outcome: "submitted", run_id: RUN({}).id } }); });
  await openTab(page);
  await page.clock.install();
  await page.getByTestId("speed-start-download").click();
  await expect(page.getByTestId("speed-pending")).toBeVisible();
  await page.clock.fastForward("21:00");                                                                               // passa qualquer prazo: o relógio não prova nada
  await expect(page.getByTestId("speed-pending")).toContainText("Aguardando a leitura mostrar a execução");
  await expect(page.getByTestId("speed-start-download")).toBeDisabled();
  await expect(page.getByTestId("speed-start-upload")).toBeDisabled();
  mode = "other";                                                                                                      // a execução de OUTRA pessoa aparece: não é a deste pedido
  await page.getByTestId("speed-pending-refresh").click();
  await expect(page.getByTestId("speed-pending")).toBeVisible();
  await expect(page.getByTestId("speed-start-download")).toBeDisabled();
  mode = "mine";
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
  await page.route("**/bff/cpes/*/speed/runs", (r) => r.fulfill({ status: 201, json: { ok: true, outcome: "submitted", run_id: RUN({}).id } }));
  await openTab(page);
  await page.getByTestId("speed-start-download").click();                                                                // a leitura seguinte (a 2ª, logo após o pedido, ainda vem vazia; a 3ª, do acompanhamento, responde 401)
  await expect(page.getByTestId("speed-error")).toContainText("Sua sessão expirou", { timeout: 15_000 });
  await expect(page.getByRole("link", { name: "Entrar de novo" })).toHaveAttribute("href", "/login");
  await expect(page.getByTestId("speed-start-download")).toHaveCount(0);
  const seen = reads;
  await page.waitForTimeout(5000);                                                                                       // mais de um ciclo de acompanhamento
  expect(reads).toBe(seen);                                                                                              // parou de consultar
});

test("teste de banda (cenário): resposta 502 ao pedido é ambígua, trava os botões, não destrava pelo relógio e Confirmar pedido repete O MESMO pedido", async ({ page, request }) => {
  await confirmDemoA2(request);
  const sent: { key: string; body: string }[] = [];
  let showRun = false;
  await page.route("**/bff/cpes/*/speed", (r) => r.fulfill({ json: { caps: CAPS(), runs: showRun ? [RUN({ status: "awaiting_approval" })] : [] } }));
  await page.route("**/bff/cpes/*/speed/runs", (r) => {
    const b = r.request().postDataJSON() as { key: string };
    sent.push({ key: b.key, body: JSON.stringify(b) });
    return sent.length === 1 ? r.fulfill({ status: 502, json: { error: "failed" } }) : r.fulfill({ status: 200, json: { ok: true, outcome: "existing", run_id: RUN({}).id } });
  });
  await openTab(page);
  await page.clock.install();
  await page.getByTestId("speed-start-download").click();
  await expect(page.getByTestId("speed-refusal")).toContainText("Use Confirmar pedido");
  await expect(page.getByTestId("speed-pending")).toContainText("a confirmação não chegou");
  await expect(page.getByTestId("speed-start-download")).toBeDisabled();
  await expect(page.getByTestId("speed-start-upload")).toBeDisabled();
  await page.clock.fastForward("30:00");                                                                                // nem o tempo, nem uma leitura sem a execução destravam
  await page.getByTestId("speed-pending-refresh").click();
  await expect(page.getByTestId("speed-start-download")).toBeDisabled();
  await expect(page.getByTestId("speed-pending-confirm")).toBeVisible();
  showRun = true;
  await page.getByTestId("speed-pending-confirm").click();                                                              // repete o MESMO pedido
  await expect(page.getByTestId("speed-active")).toContainText("Aguardando aprovação");
  await expect(page.getByTestId("speed-pending")).toHaveCount(0);
  expect(sent).toHaveLength(2);
  expect(sent[1]!.key).toBe(sent[0]!.key);                                                                              // MESMA chave de idempotência...
  expect(sent[1]!.body).toBe(sent[0]!.body);                                                                            // ...e MESMA intenção
});

test("teste de banda (cenário): se a confirmação do pedido incerto é recusada de forma definitiva, a trava sai", async ({ page, request }) => {
  await confirmDemoA2(request);
  let posts = 0;
  await page.route("**/bff/cpes/*/speed", (r) => r.fulfill({ json: { caps: CAPS(), runs: [] } }));
  await page.route("**/bff/cpes/*/speed/runs", (r) => { posts += 1; return posts === 1 ? r.fulfill({ status: 502, json: { error: "failed" } }) : r.fulfill({ status: 409, json: { error: "blocked", reason: "tenant_busy" } }); });
  await openTab(page);
  await page.getByTestId("speed-start-download").click();
  await expect(page.getByTestId("speed-pending-confirm")).toBeVisible();
  await page.getByTestId("speed-pending-confirm").click();
  await expect(page.getByTestId("speed-refusal")).toContainText("limite de testes simultâneos");
  await expect(page.getByTestId("speed-pending")).toHaveCount(0);
  await expect(page.getByTestId("speed-start-download")).toBeEnabled();
});

test("teste de banda (cenário): sem como guardar a trava no navegador, o pedido NÃO sai", async ({ page, request }) => {
  await confirmDemoA2(request);
  let posts = 0;
  await page.addInitScript(() => { Storage.prototype.setItem = () => { throw new Error("cheio"); }; });
  await page.route("**/bff/cpes/*/speed", (r) => r.fulfill({ json: { caps: CAPS(), runs: [] } }));
  await page.route("**/bff/cpes/*/speed/runs", (r) => { posts += 1; return r.fulfill({ status: 201, json: { ok: true, outcome: "submitted", run_id: RUN({}).id } }); });
  await openTab(page);
  await page.getByTestId("speed-start-download").click();
  await expect(page.getByTestId("speed-refusal")).toContainText("não permite guardar o pedido em andamento");
  await expect(page.getByTestId("speed-pending")).toHaveCount(0);
  expect(posts).toBe(0);
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

test("teste de banda (cenário): fechar o painel ou trocar de aba não destrava um pedido ainda não esclarecido", async ({ page, request }) => {
  await confirmDemoA2(request);
  let posts = 0;
  await page.route("**/bff/cpes/*/speed", (r) => r.fulfill({ json: { caps: CAPS(), runs: [] } }));          // a leitura nunca mostra a execução
  await page.route("**/bff/cpes/*/speed/runs", (r) => { posts += 1; return r.fulfill({ status: 201, json: { ok: true, outcome: "submitted", run_id: RUN({}).id } }); });
  await openTab(page);
  await page.getByTestId("speed-start-download").click();
  await expect(page.getByTestId("speed-pending")).toBeVisible();
  await page.getByRole("tab", { name: "Resumo" }).click();                                                    // sai da aba: a seção desmonta
  await page.getByRole("tab", { name: "Teste de banda" }).click();                                            // e volta
  await expect(page.getByTestId("speed-pending")).toBeVisible();
  await expect(page.getByTestId("speed-start-download")).toBeDisabled();
  await page.getByTestId("onu-quick-close").click();                                                          // fecha o painel e reabre a mesma ONU
  await row(page, "DEMOA0002").click();
  await page.getByRole("tab", { name: "Teste de banda" }).click();
  await expect(page.getByTestId("speed-pending")).toBeVisible();
  await expect(page.getByTestId("speed-start-download")).toBeDisabled();
  await page.reload();                                                                                         // e até recarregar a página (mesma sessão do navegador)
  await row(page, "DEMOA0002").click();
  await page.getByRole("tab", { name: "Teste de banda" }).click();
  await expect(page.getByTestId("speed-pending")).toBeVisible();
  await expect(page.getByTestId("speed-start-upload")).toBeDisabled();
  expect(posts).toBe(1);
});

test("teste de banda (cenário): Confirmar pedido repete a MESMA chave, a MESMA intenção e o MESMO group_id de um teste agrupado", async ({ page, request }) => {
  await confirmDemoA2(request);
  const upload = RUN({ id: "44444444-4444-4444-8444-444444444444", direction: "upload", status: "completed", mbps: 40, reliable: true, bytes: 10_000_000, duration_ms: 8000 });
  const sent: { key: string; body: string; group_id?: string }[] = [];
  await page.route("**/bff/cpes/*/speed", (r) => r.fulfill({ json: { caps: CAPS(), runs: [upload] } }));
  await page.route("**/bff/cpes/*/speed/runs", (r) => {
    const b = r.request().postDataJSON() as { key: string; group_id?: string };
    sent.push({ key: b.key, body: JSON.stringify(b), group_id: b.group_id });
    return sent.length === 1 ? r.fulfill({ status: 502, json: { error: "failed" } }) : r.fulfill({ status: 200, json: { ok: true, outcome: "existing", run_id: RUN({}).id } });
  });
  await openTab(page);
  await page.getByTestId("speed-start-download").click();                                                               // o upload anterior (10mb, mesmo destino) vira o mesmo grupo
  await expect(page.getByTestId("speed-pending-confirm")).toBeVisible();
  await page.getByTestId("speed-pending-confirm").click();
  await expect.poll(() => sent.length).toBe(2);
  expect(sent[0]!.group_id).toBe(upload.group_id);
  expect(sent[1]!.key).toBe(sent[0]!.key);
  expect(sent[1]!.body).toBe(sent[0]!.body);                                                                            // inclui o group_id
});

test("teste de banda (cenário): um marcador guardado com runId malformado é descartado, nunca interpretado", async ({ page, request }) => {
  await confirmDemoA2(request);
  await page.route("**/bff/cpes/*/speed", (r) => r.fulfill({ json: { caps: CAPS(), runs: [] } }));
  await page.route("**/bff/cpes/*/speed/runs", (r) => r.fulfill({ status: 201, json: { ok: true, outcome: "submitted", run_id: RUN({}).id } }));
  await openTab(page);
  await page.getByTestId("speed-start-download").click();
  await expect(page.getByTestId("speed-pending")).toBeVisible();
  // a página viva regrava o marcador do estado em memória a cada atualização: a adulteração entra no INÍCIO do documento seguinte, depois de todas as escritas da página antiga
  await page.addInitScript(() => {
    for (let i = 0; i < sessionStorage.length; i++) {
      const k = sessionStorage.key(i)!;
      if (k.startsWith("fc-speed-pending:")) { const o = JSON.parse(sessionStorage.getItem(k)!); o.runId = "não-é-uuid"; sessionStorage.setItem(k, JSON.stringify(o)); }
    }
  });
  await page.reload();
  await row(page, "DEMOA0002").click();
  await page.getByRole("tab", { name: "Teste de banda" }).click();
  await expect(page.getByTestId("speed-pending")).toHaveCount(0);                                                       // formato inválido: o marcador não vale
  await expect(page.getByTestId("speed-start-download")).toBeEnabled();
});
