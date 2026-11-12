import AxeBuilder from "@axe-core/playwright";
import { readFileSync } from "node:fs";
import { expect, test, type APIRequestContext } from "@playwright/test";
import { API_URL, EMAIL, login, PASSWORD } from "./helpers";

// ACS por organização (ADR-0046 D2), contra a stack real: cadastro, o EDGE SIMULADO pelo teste informa o estado (POST /v1/edge/acs-status), renomear, ativar/desativar,
// um ativo por Edge, sem JavaScript e axe. Precisa de E2E_EDGE_CREDS_FILE (seed_demo.py/scripts/e2e.sh) e da flag `acs_registry` ligada.
const SUFFIX = String(Date.now()).slice(-6);
const creds = () => (process.env.E2E_EDGE_CREDS_FILE ? (JSON.parse(readFileSync(process.env.E2E_EDGE_CREDS_FILE, "utf8")) as { client_id: string; client_secret: string }) : null);

async function edgeHeaders(request: APIRequestContext) {
  const r = await request.post(`${API_URL}/v1/auth/service-token`, { data: creds()! });
  expect(r.status()).toBe(200);
  return { Authorization: `Bearer ${(await r.json()).access_token as string}` };
}
const report = (request: APIRequestContext, h: Record<string, string>, id: string, body: Record<string, unknown>) =>
  request.post(`${API_URL}/v1/edge/acs-status`, { headers: h, data: { acs_id: id, kind: "genieacs", ...body } });

/** Um ACS ativo por Edge: o que a captura da ajuda (ou uma execução anterior) deixou ativo é desativado, para o cadastro deste teste começar limpo. */
async function deactivateAll(request: APIRequestContext) {
  const tok = (await (await request.post(`${API_URL}/v1/auth/token`, { data: { email: EMAIL, password: PASSWORD } })).json()).access_token as string;
  const h = { Authorization: `Bearer ${tok}` };
  const list = ((await (await request.get(`${API_URL}/v1/acs`, { headers: h })).json()) as { items: { id: string; enabled: boolean }[] }).items;
  for (const a of list) if (a.enabled) expect((await request.patch(`${API_URL}/v1/acs/${a.id}`, { headers: h, data: { enabled: false } })).status()).toBe(200);
}

test("acs: cadastra, o Edge informa, renomeia, troca o ativo e a tela nunca pede URL nem senha", async ({ page, request, browser, context }) => {
  test.skip(!creds(), "defina E2E_EDGE_CREDS_FILE (seed_demo.py/scripts/e2e.sh) e ligue a flag acs_registry");
  await deactivateAll(request);
  await login(page);
  await page.goto("/rede");
  await page.getByTestId("rede-acs-link").click();
  await expect(page).toHaveURL(/\/rede\/acs$/);
  await expect(page.getByRole("heading", { name: "ACS", level: 1 })).toBeVisible();
  const cad = page.getByTestId("acs-cadastro");
  await expect(cad).toContainText("a URL e a senha do GenieACS ficam no Edge");
  await expect(cad.locator("input[type=password]")).toHaveCount(0);                                  // nenhum campo de senha, URL ou host
  await expect(cad.getByLabel(/url|host|endere/i)).toHaveCount(0);
  // cadastro (ativo) e o aviso do identificador
  const name = `Genie E2E ${SUFFIX}`;
  await cad.getByLabel("Nome do ACS").fill(name);
  await cad.getByLabel("Rótulo (opcional)").fill("ACS do laboratório");
  await page.getByTestId("acs-cadastrar").click();
  await expect(page.getByTestId("acs-flash")).toContainText("nbi_cloud_id");
  const item = page.getByTestId("acs-item").filter({ hasText: name });
  await expect(item).toHaveCount(1);
  await expect(item.getByTestId("acs-ativo")).toHaveText(/Ativo/);
  await expect(item.getByTestId("acs-saude")).toHaveText(/Sem leitura/);                              // nada foi lido ainda: nunca um "ok" inventado
  await expect(item.getByTestId("acs-visto")).toHaveText("ainda não visto");
  await expect(item.getByTestId("acs-dispositivos")).toHaveText("—");
  await expect(item).toContainText("ACS do laboratório");
  const id = (await item.getByTestId("acs-id").textContent())!.trim();
  expect(id).toMatch(/^[0-9a-f-]{36}$/);
  // o mesmo nome neste Edge e um segundo ACS ativo são recusados com a mensagem certa, e nenhum texto digitado volta
  await cad.getByLabel("Nome do ACS").fill(name.toUpperCase());
  await page.getByTestId("acs-cadastrar").click();
  await expect(page.getByTestId("acs-flash")).toContainText("Este Edge já tem um ACS ativo");
  await cad.getByLabel("Nome do ACS").fill("Outro");
  await cad.getByLabel("Ativar agora").uncheck();
  await page.getByTestId("acs-cadastrar").click();
  await expect(page.getByTestId("acs-item").filter({ hasText: "Outro" }).getByTestId("acs-ativo")).toHaveText(/Inativo/);
  await cad.getByLabel("Nome do ACS").fill(name.toLowerCase());
  await cad.getByLabel("Ativar agora").uncheck();
  await page.getByTestId("acs-cadastrar").click();
  await expect(page.getByTestId("acs-flash")).toContainText("Já existe um ACS com esse nome");
  // o EDGE (simulado) informa: ok com 42 dispositivos
  const h = await edgeHeaders(request);
  expect((await report(request, h, id, { ok: true, device_count: 42, error_code: null })).status()).toBe(204);
  await page.goto("/rede/acs");
  const ok = page.getByTestId("acs-item").filter({ hasText: name });
  await expect(ok.getByTestId("acs-saude")).toHaveText(/Respondendo/);
  await expect(ok.getByTestId("acs-dispositivos")).toHaveText("42 dispositivos");
  await expect(ok.getByTestId("acs-visto")).toHaveText("visto agora há pouco");
  await expect(ok.getByTestId("acs-erro")).toHaveText("nenhum");
  // falha: o texto em português e a última contagem boa preservada
  expect((await report(request, h, id, { ok: false, device_count: null, error_code: "unauthorized" })).status()).toBe(204);
  await page.goto("/rede/acs");
  const bad = page.getByTestId("acs-item").filter({ hasText: name });
  await expect(bad.getByTestId("acs-saude")).toHaveText(/Com falha/);
  await expect(bad.getByTestId("acs-erro")).toContainText("recusou o usuário e a senha do NBI");
  await expect(bad.getByTestId("acs-dispositivos")).toHaveText("42 dispositivos");
  // um id que não é deste Edge, ou um tipo errado, é o mesmo 404 e não cria nada
  const unknown = await report(request, h, "11111111-1111-4111-8111-111111111111", { ok: true, device_count: 1, error_code: null });
  const wrongKind = await request.post(`${API_URL}/v1/edge/acs-status`, { headers: h, data: { acs_id: id, kind: "zabbix", ok: true, device_count: 1, error_code: null } });
  expect([unknown.status(), wrongKind.status()]).toEqual([404, 404]);
  expect(await unknown.json()).toEqual(await wrongKind.json());
  // renomear: o identificador e o estado ficam
  await bad.getByText("Renomear", { exact: false }).first().click();
  await bad.getByLabel("Nome", { exact: true }).fill(`${name} (matriz)`);
  await bad.getByTestId("acs-salvar").click();
  await expect(page.getByTestId("acs-flash")).toContainText("ACS atualizado");
  const renamed = page.getByTestId("acs-item").filter({ hasText: `${name} (matriz)` });
  await expect(renamed.getByTestId("acs-id")).toHaveText(id);
  await expect(renamed.getByTestId("acs-dispositivos")).toHaveText("42 dispositivos");
  // ativar o segundo com o primeiro ativo é recusado; desativar o primeiro libera a vaga
  const second = page.getByTestId("acs-item").filter({ hasText: "Outro" });
  await second.getByTestId("acs-alternar").click();
  await expect(page.getByTestId("acs-flash")).toContainText("Este Edge já tem um ACS ativo");
  await renamed.getByTestId("acs-alternar").click();
  await expect(page.getByTestId("acs-flash")).toContainText("ACS desativado");
  await expect(page.getByTestId("acs-item").filter({ hasText: `${name} (matriz)` }).getByTestId("acs-ativo")).toHaveText(/Inativo/);
  await page.getByTestId("acs-item").filter({ hasText: "Outro" }).getByTestId("acs-alternar").click();
  await expect(page.getByTestId("acs-flash")).toContainText("ACS ativado");
  const res = await new AxeBuilder({ page: page as never }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  expect(res.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => v.id)).toEqual([]);
  // sem JavaScript os formulários seguem funcionando (reativa o primeiro: desativa o "Outro" antes)
  const state = await context.storageState();
  const noJs = await browser.newContext({ javaScriptEnabled: false, storageState: state, baseURL: process.env.WEB_URL ?? "http://127.0.0.1:3000" });
  const p2 = await noJs.newPage();
  await p2.goto("/rede/acs");
  await p2.getByTestId("acs-item").filter({ hasText: "Outro" }).getByTestId("acs-alternar").click();
  await expect(p2.getByTestId("acs-flash")).toContainText("ACS desativado");
  await p2.getByTestId("acs-item").filter({ hasText: `${name} (matriz)` }).getByTestId("acs-alternar").click();
  await expect(p2.getByTestId("acs-flash")).toContainText("ACS ativado");
  await noJs.close();
  // mobile: sem rolagem horizontal
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/rede/acs");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("acs: um engenheiro (acs:read sem acs:manage) só vê: a tela não oferece cadastro nem troca", async ({ page }) => {
  test.skip(!creds(), "defina E2E_EDGE_CREDS_FILE (seed_demo.py/scripts/e2e.sh) e ligue a flag acs_registry");
  await login(page, process.env.ACS_READONLY_EMAIL ?? "agente@demo.example.com");   // o seed cria o "Agente Demo" com o papel engineer
  await page.goto("/rede/acs");
  await expect(page.getByTestId("acs-somente-leitura")).toBeVisible();
  await expect(page.getByTestId("acs-cadastro")).toHaveCount(0);
  await expect(page.getByTestId("acs-alternar")).toHaveCount(0);
  await expect(page.getByTestId("acs-lista")).toBeVisible();
});
