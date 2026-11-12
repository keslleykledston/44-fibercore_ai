import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { API_URL, EMAIL, login, PASSWORD } from "./helpers";

// Organizações da plataforma (ADR-0046 D1), contra a stack real: só a conta operadora vê a tela (os outros recebem 404 e não veem o item); sem MFA recente a tela pede o segundo fator (formulário
// comum); criação sem JavaScript com o link do convite UMA vez; nome repetido; limite de 5 por hora; lista só com contagens; axe. A conta operadora é a do seed (suporte@plataforma.example.com).
const OPERATOR = "suporte@plataforma.example.com";
const SUFFIX = String(Date.now()).slice(-6);
const NAME = `Provedor E2E ${SUFFIX}`;
const BASE = process.env.WEB_URL ?? "http://127.0.0.1:3000";

async function operatorLogin(page: Page, code?: string) {
  await page.goto("/login");
  await page.getByLabel("E-mail").fill(OPERATOR);
  await page.getByLabel("Senha").fill(PASSWORD);
  await page.getByRole("button", { name: "Entrar" }).click();
  if (code) {
    await page.getByLabel(/Código do aplicativo/).fill(code);
    await page.getByRole("button", { name: /Verificar|Entrar|Confirmar/ }).click();
  }
  await page.waitForURL((u) => !u.pathname.startsWith("/login"));
}

test.describe.configure({ mode: "serial" });

test("quem não é operador não vê o item e recebe 404 na tela e 403 na API", async ({ page, request }) => {
  await login(page);                                           // administrador do provedor demo
  await page.goto("/administracao/equipe");
  await expect(page.getByRole("heading", { name: "Equipe e acessos" })).toBeVisible();
  await expect(page.getByTestId("admin-tab-organizacoes")).toHaveCount(0);
  const r = await page.goto("/plataforma/organizacoes");
  expect(r?.status()).toBe(404);
  await expect(page.getByRole("heading", { name: "Página não encontrada" })).toBeVisible();
  const tok = (await (await request.post(`${API_URL}/v1/auth/token`, { data: { email: EMAIL, password: PASSWORD } })).json()).access_token as string;
  for (const path of ["/v1/platform/organizations"]) expect((await request.get(`${API_URL}${path}`, { headers: { Authorization: `Bearer ${tok}` } })).status()).toBe(403);
  expect((await request.post(`${API_URL}/v1/platform/organizations`, { headers: { Authorization: `Bearer ${tok}` }, data: { name: "Invasao", admin_email: "x@example.com" } })).status()).toBe(403);
});

let recovery: string[] = [];

test("operador sem segundo fator recente: a tela pede o código (formulário comum) e só depois mostra a lista", async ({ page, request }) => {
  await operatorLogin(page);                                    // ainda sem MFA: a sessão não tem prova do segundo fator
  await page.goto("/administracao/modulos");
  await expect(page.getByTestId("admin-tab-organizacoes")).toBeVisible();     // o item aparece para o operador
  await page.getByTestId("admin-tab-organizacoes").click();
  await expect(page.getByTestId("org-mfa")).toBeVisible();
  await expect(page.getByTestId("org-lista")).toHaveCount(0);
  await page.getByLabel("Código do autenticador").fill("000000");
  await page.getByTestId("org-mfa-enviar").click();
  await expect(page.getByTestId("org-erro")).toContainText("ainda não ativou o MFA");   // a API respondeu 409 not_enrolled

  // o operador ativa o MFA (pela API, como a tela Conta → Segurança) e confirma com um código de recuperação
  const tok = (await (await request.post(`${API_URL}/v1/auth/token`, { data: { email: OPERATOR, password: PASSWORD } })).json()).access_token as string;
  const h = { Authorization: `Bearer ${tok}` };
  const secret = (await (await request.post(`${API_URL}/v1/auth/mfa/enroll`, { headers: h, data: { password: PASSWORD } })).json()).secret as string;
  const { totp } = await import("./helpers");
  const act = await request.post(`${API_URL}/v1/auth/mfa/activate`, { headers: h, data: { code: totp(secret) } });
  expect(act.status()).toBe(200);
  recovery = (await act.json()).recovery_codes as string[];
  await page.goto("/plataforma/organizacoes");
  await page.getByLabel("Código do autenticador").fill("000000");
  await page.getByTestId("org-mfa-enviar").click();
  await expect(page.getByTestId("org-erro")).toContainText("Código inválido");
  await page.getByLabel("Código do autenticador").fill(recovery[0]);
  await page.getByTestId("org-mfa-enviar").click();
  await expect(page.getByTestId("org-flash")).toContainText("Segundo fator confirmado");
  await expect(page.getByTestId("org-lista")).toBeVisible();
  await expect(page.getByTestId("org-linha").first()).toBeVisible();          // a organização demo
});

test("criar organização sem JavaScript: link do convite uma vez, lista com contagens, nome repetido e acessibilidade", async ({ browser, page }) => {
  await operatorLogin(page, recovery[1]);                      // entra de novo, agora com MFA (login em duas etapas)
  await page.goto("/plataforma/organizacoes");                  // acessibilidade COM JavaScript (o axe precisa dele); a criação abaixo é SEM JavaScript
  await expect(page.getByTestId("org-nova")).toBeVisible();
  await expect(page.getByTestId("org-mfa")).toHaveCount(0);     // o login com MFA já conta como recente
  const ax = await new AxeBuilder({ page: page as never }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  expect(ax.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" || ")}`)).toEqual([]);
  for (const el of await page.getByTestId("org-nova").locator("input, button").all()) {
    const box = await el.boundingBox();
    if (box) expect(Math.min(box.width, box.height)).toBeGreaterThanOrEqual(24);
  }
  const state = await page.context().storageState();
  const noJs = await browser.newContext({ javaScriptEnabled: false, storageState: state, baseURL: BASE });
  const p = await noJs.newPage();
  await p.goto("/plataforma/organizacoes");
  await expect(p.getByTestId("org-nova")).toBeVisible();
  await expect(p.getByTestId("org-lista")).toContainText("Só contagens e rótulos");
  await p.getByLabel("Nome da organização").fill(NAME);
  await p.getByLabel("E-mail do primeiro administrador").fill(`admin.${SUFFIX}@exemplo.com.br`);
  await p.getByLabel(/Nome do primeiro administrador/).fill("Ana Administradora");
  await p.getByTestId("org-criar").click();
  await expect(p.getByTestId("org-criada")).toContainText(NAME);
  await expect(p.getByTestId("org-convite-estado")).toHaveText("pendente");
  const link = await p.getByTestId("org-convite-link").inputValue();
  expect(link).toMatch(new RegExp(`^${BASE.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}/convite/[A-Za-z0-9_-]{43}$`));
  expect(p.url()).not.toContain(link.split("/").pop()!);       // o token nunca vai na URL
  await expect(p.getByTestId("org-lista")).toContainText(NAME);
  const row = p.getByTestId("org-linha").filter({ hasText: NAME });
  await expect(row).toContainText("Pendente");
  await expect(row).toContainText("pela tela");
  expect(await row.innerText()).toMatch(/0\s+0\s+0/);          // vazia: sem Edge, OLT nem ONU
  expect(await p.locator("main").innerText()).not.toMatch(/DEMOA\d{4}/);   // nenhum serial de ONU na tela
  // nada de segredo na página depois de ocultar
  await p.getByRole("button", { name: "Ocultar o link" }).click();
  await expect(p.getByTestId("org-flash")).toContainText("ocultado");
  await expect(p.getByTestId("org-convite-link")).toHaveCount(0);
  // o convite vale: a pessoa convidada o abre (página pública) e vê o nome da organização
  const inv = await browser.newContext({ baseURL: BASE });
  const ip = await inv.newPage();
  await ip.goto(new URL(link).pathname);
  await expect(ip.locator("main")).toContainText(NAME);
  await inv.close();
  // nome repetido (sem diferenciar maiúsculas) é recusado em português e a lista não duplica
  await p.getByLabel("Nome da organização").fill(NAME.toUpperCase());
  await p.getByLabel("E-mail do primeiro administrador").fill(`outro.${SUFFIX}@exemplo.com.br`);
  await p.getByTestId("org-criar").click();
  await expect(p.getByTestId("org-erro")).toContainText("Já existe uma organização com esse nome");
  await expect(p.getByTestId("org-linha").filter({ hasText: NAME })).toHaveCount(1);
  await noJs.close();
});

test("limite de 5 por hora: a sexta é recusada em português", async ({ page, request }) => {
  await operatorLogin(page, recovery[2]);
  const tok = await (async () => {
    const t = await (await request.post(`${API_URL}/v1/auth/token`, { data: { email: OPERATOR, password: PASSWORD } })).json();
    const v = await request.post(`${API_URL}/v1/auth/mfa/verify`, { data: { mfa_token: t.mfa_token, code: recovery[3] } });
    expect(v.status()).toBe(200);
    return (await v.json()).access_token as string;
  })();
  for (let i = 2; i <= 5; i++) {                                // a primeira (tela) já foi criada acima; mais 4 pela API até o teto
    const r = await request.post(`${API_URL}/v1/platform/organizations`, { headers: { Authorization: `Bearer ${tok}` }, data: { name: `Lote E2E ${SUFFIX} ${i}`, admin_email: `lote${i}.${SUFFIX}@exemplo.com.br` } });
    expect(r.status(), await r.text()).toBe(201);
  }
  await page.goto("/plataforma/organizacoes");
  await page.getByLabel("Nome da organização").fill(`Sexta E2E ${SUFFIX}`);
  await page.getByLabel("E-mail do primeiro administrador").fill(`sexta.${SUFFIX}@exemplo.com.br`);
  await page.getByTestId("org-criar").click();
  await expect(page.getByTestId("org-erro")).toContainText("Limite de 5 organizações por hora");
  await expect(page.getByTestId("org-linha").filter({ hasText: `Sexta E2E ${SUFFIX}` })).toHaveCount(0);
});
