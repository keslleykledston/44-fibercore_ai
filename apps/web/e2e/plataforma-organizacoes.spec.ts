import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { API_URL, EMAIL, login, PASSWORD } from "./helpers";

// Organizações da plataforma (ADR-0046 D1), contra a stack real: só a conta operadora vê a tela (os outros recebem 404 e não veem o item); sem MFA recente a tela pede o segundo fator (formulário
// comum); criação sem JavaScript com o link do convite UMA vez; nome repetido; limite de 5 por hora; lista só com contagens; axe. A conta operadora é a do seed (suporte@plataforma.example.com).
const OPERATOR = "suporte@plataforma.example.com";
const SUFFIX = String(Date.now()).slice(-6);
const NAME = `Provedor E2E ${SUFFIX}`;
const BASE = process.env.WEB_URL ?? "http://127.0.0.1:3000";

async function operatorLogin(page: Page, code?: string, email: string = OPERATOR) {
  await page.goto("/login");
  await page.getByLabel("E-mail").fill(email);
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
let jsInvite = "";    // token do convite da organização criada com JavaScript (a pessoa convidada vira administradora dela no último teste)

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
  expect(link).toMatch(/^\/convite\/[A-Za-z0-9_-]{43}$/);          // sem JavaScript: só o CAMINHO (nenhum cabeçalho de host entra no link)
  await expect(p.getByTestId("org-convite-sem-js")).toBeVisible();
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
  await ip.goto(link);
  await expect(ip.locator("main")).toContainText(NAME);
  await inv.close();
  // nome repetido (sem diferenciar maiúsculas) é recusado em português e a lista não duplica
  await p.getByLabel("Nome da organização").fill(NAME.toUpperCase());
  await p.getByLabel("E-mail do primeiro administrador").fill(`outro.${SUFFIX}@exemplo.com.br`);
  await p.getByTestId("org-criar").click();
  await expect(p.getByTestId("org-erro")).toContainText("Já existe uma organização com esse nome");
  await expect(p.getByTestId("org-linha").filter({ hasText: NAME })).toHaveCount(1);
  await noJs.close();
  // com JavaScript o link sai inteiro, com a origem do NAVEGADOR, e há o botão de copiar
  await page.goto("/plataforma/organizacoes");
  await page.getByLabel("Nome da organização").fill(`${NAME} JS`);
  await page.getByLabel("E-mail do primeiro administrador").fill(`js.${SUFFIX}@exemplo.com.br`);
  await page.getByTestId("org-criar").click();
  await expect(page.getByTestId("org-criada")).toContainText(`${NAME} JS`);
  await expect(page.getByTestId("org-convite-link")).toHaveValue(new RegExp(`^${BASE.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}/convite/[A-Za-z0-9_-]{43}$`));
  jsInvite = (await page.getByTestId("org-convite-link").inputValue()).split("/").pop()!;
  await expect(page.getByTestId("org-convite-copiar")).toBeVisible();
  await expect(page.getByTestId("org-convite-sem-js")).toHaveCount(0);
});

test("limite de 5 por hora: a sexta é recusada em português", async ({ page, request }) => {
  await operatorLogin(page, recovery[2]);
  const tok = await (async () => {
    const t = await (await request.post(`${API_URL}/v1/auth/token`, { data: { email: OPERATOR, password: PASSWORD } })).json();
    const v = await request.post(`${API_URL}/v1/auth/mfa/verify`, { data: { mfa_token: t.mfa_token, code: recovery[3] } });
    expect(v.status()).toBe(200);
    return (await v.json()).access_token as string;
  })();
  for (let i = 3; i <= 5; i++) {                                // duas (tela) já foram criadas acima; mais 3 pela API até o teto
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

test("ciclo de vida: detalhe, recursos, renomear, suspender (o usuário vê o aviso e a API bloqueia) e reativar", async ({ browser, page, request }) => {
  const ADMIN = `js.${SUFFIX}@exemplo.com.br`;       // o e-mail do convite da organização criada com JavaScript
  const acc = await request.post(`${API_URL}/v1/invites/${jsInvite}/accept`, { data: { name: "Ana JS", password: PASSWORD } });
  expect(acc.status(), await acc.text()).toBeLessThan(300);
  const org = `${NAME} JS`;
  await operatorLogin(page, recovery[4]);
  await page.goto("/plataforma/organizacoes");
  await page.getByTestId("org-linha").filter({ hasText: org }).getByTestId("org-detalhe-link").click();
  await expect(page.getByRole("heading", { name: org })).toBeVisible();
  await expect(page.getByTestId("org-estado")).toContainText("Ativa");
  await expect(page.getByTestId("org-saude")).toContainText("Edges online");
  const ax = async (scope?: string) => (await (scope ? new AxeBuilder({ page: page as never }).include(scope) : new AxeBuilder({ page: page as never })).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze())
    .violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" || ")}`);
  await page.setViewportSize({ width: 1280, height: 2600 });
  expect(await ax()).toEqual([]);
  await page.emulateMedia({ colorScheme: "dark" });
  expect(await ax("main")).toEqual([]);      // o item ativo do menu no escuro é do AppShell (fora desta entrega): aqui só o conteúdo da tela
  await page.emulateMedia({ colorScheme: "light" });

  // recursos: um recurso comum liga e desliga com motivo; um que escreve na rede não oferece "Ligar"
  const row = (f: string) => page.locator(`[data-testid="org-recurso"][data-feature="${f}"]`);
  const owner = row("bench_writes");
  await expect(owner.getByTestId("org-recurso-dono")).toContainText("Só o dono liga");
  await expect(owner.locator("select option")).toHaveText(["Desligar", "Voltar ao padrão"]);
  await expect(row("onu_discovery").getByTestId("org-recurso-atual")).toHaveText("Desligado");
  await row("onu_discovery").locator("select").selectOption("on");
  await row("onu_discovery").getByLabel(/Motivo da mudança/).fill("Piloto do cliente");
  await row("onu_discovery").getByRole("button", { name: "Aplicar" }).click();
  await expect(page.getByTestId("org-flash")).toContainText("Recurso atualizado");
  await expect(row("onu_discovery").getByTestId("org-recurso-atual")).toHaveText("Ligado");
  await row("onu_discovery").locator("select").selectOption("off");
  await row("onu_discovery").getByLabel(/Motivo da mudança/).fill("Fim do piloto");
  await row("onu_discovery").getByRole("button", { name: "Aplicar" }).click();
  await expect(row("onu_discovery").getByTestId("org-recurso-atual")).toHaveText("Desligado");

  // limites técnicos (ADR-0047 D3): padrão, ajuste com motivo, selo "ajustado" e volta ao padrão
  const lim = (k: string) => page.locator(`[data-testid="org-limite"][data-limit="${k}"]`);
  await expect(page.getByTestId("org-limites")).toContainText("nada existente é removido");
  await expect(page.getByTestId("org-limites")).not.toContainText(/plano|preço|cobrança/i);
  await expect(lim("max_olts").getByTestId("org-limite-origem")).toHaveText("padrão");
  await expect(lim("max_edges").getByTestId("org-limite-uso")).toHaveText("0");
  await lim("max_olts").getByRole("spinbutton").fill("7");
  await lim("max_members").getByRole("checkbox").check();
  await page.getByTestId("org-limites").getByLabel(/Motivo/).fill("Piloto pequeno");
  await page.getByTestId("org-limites-enviar").click();
  await expect(page.getByTestId("org-flash")).toContainText("Limites atualizados");
  await expect(lim("max_olts").getByTestId("org-limite-vigor")).toHaveText("7");
  await expect(lim("max_olts").getByTestId("org-limite-origem")).toHaveText("ajustado");
  await expect(lim("max_members").getByTestId("org-limite-origem")).toHaveText("padrão");
  await page.getByTestId("org-limites").getByLabel(/Motivo/).fill("Sem mudança");     // nada preenchido: nada muda (mensagem de erro curta)
  await page.getByTestId("org-limites-enviar").click();
  await expect(page.getByTestId("org-erro")).toContainText("Preencha pelo menos um campo");
  await lim("max_olts").getByRole("checkbox").check();
  await page.getByTestId("org-limites").getByLabel(/Motivo/).fill("Voltou ao padrão");
  await page.getByTestId("org-limites-enviar").click();
  await expect(lim("max_olts").getByTestId("org-limite-origem")).toHaveText("padrão");
  await expect(page.getByTestId("org-historico")).toContainText("OLTs: padrão → 7");
  await expect(page.getByTestId("org-historico")).toContainText("OLTs: 7 → padrão");

  // renomear
  await page.getByLabel(/Novo nome/).fill(`${org} Renomeada`);
  await page.getByTestId("org-nome-enviar").click();
  await expect(page.getByTestId("org-flash")).toContainText("Nome da organização alterado");
  await expect(page.getByRole("heading", { name: `${org} Renomeada` })).toBeVisible();

  // a pessoa da organização entra (organização ativa)
  // o administrador da organização precisa de MFA (política do ambiente): ativa pela API e entra em duas etapas, como a tela de Conta → Segurança faz
  const at = (await (await request.post(`${API_URL}/v1/auth/token`, { data: { email: ADMIN, password: PASSWORD } })).json()).access_token as string;
  const ah = { Authorization: `Bearer ${at}` };
  const enr = await request.post(`${API_URL}/v1/auth/mfa/enroll`, { headers: ah, data: { password: PASSWORD } });
  expect(enr.status(), `${await enr.text()} (token: ${at ? "ok" : "vazio"})`).toBe(200);
  const sec = (await enr.json()).secret as string;
  const { totp } = await import("./helpers");
  const act = await request.post(`${API_URL}/v1/auth/mfa/activate`, { headers: ah, data: { code: totp(sec) } });
  expect(act.status()).toBe(200);
  const codes = (await act.json()).recovery_codes as string[];
  const ctx = await browser.newContext({ baseURL: BASE });
  const up = await ctx.newPage();
  await operatorLogin(up, codes[0], ADMIN);
  await expect(up.getByRole("heading", { name: "Visão Geral" })).toBeVisible();
  // suspender com motivo
  await page.getByTestId("org-acao-estado").getByLabel(/Motivo/).fill("Contrato encerrado");
  await page.getByTestId("org-estado-enviar").click();
  await expect(page.getByTestId("org-flash")).toContainText("Organização suspensa");
  await expect(page.getByTestId("org-estado")).toContainText("Suspensa");
  // encerramento (ADR-0050): a tela só PEDE; carência de 7 dias; cancelar; um novo pedido; reativar cancela
  const enc = page.getByTestId("org-encerramento");
  await expect(enc).toContainText("não apaga nada");
  await expect(enc).toContainText("não baixa dados");
  await expect(enc).not.toContainText(/plano|preço|cobrança/i);
  await enc.getByLabel(/Motivo do pedido/).fill("Cliente encerrou o contrato");
  await page.getByTestId("org-encerramento-pedir").click();
  await expect(page.getByTestId("org-flash")).toContainText("Nada foi apagado");
  await expect(page.getByTestId("org-encerramento-estado")).toContainText("Pedido aberto");
  await expect(page.getByTestId("org-encerramento-carencia")).not.toContainText("vencida");
  await expect(page.getByTestId("org-encerramento-aguarde")).toBeVisible();
  await expect(page.getByTestId("org-encerramento-dono")).toHaveCount(0);       // dentro da carência o dono não tem o que fazer
  expect(await ax("main")).toEqual([]);
  await enc.getByLabel(/Motivo do cancelamento/).fill("Mudou de ideia");
  await page.getByTestId("org-encerramento-cancelar").click();
  await expect(page.getByTestId("org-flash")).toContainText("Pedido de encerramento cancelado");
  await expect(page.getByTestId("org-encerramento-anterior")).toContainText("Pedido anterior cancelado");
  await enc.getByLabel(/Motivo do pedido/).fill("Pedido de novo");
  await page.getByTestId("org-encerramento-pedir").click();
  await expect(page.getByTestId("org-encerramento-estado")).toContainText("Pedido aberto");
  await page.goto("/plataforma/organizacoes");
  await expect(page.getByTestId("org-linha").filter({ hasText: `${org} Renomeada` }).getByTestId("org-estado-linha")).toContainText("Suspensa");
  // o usuário da organização vê o aviso; o motivo não aparece
  await up.goto("/");
  await expect(up.getByTestId("org-suspensa-aviso")).toContainText("Organização suspensa");
  await expect(up.locator("main, body").first()).not.toContainText("Contrato encerrado");
  const t2 = await (await request.post(`${API_URL}/v1/auth/token`, { data: { email: ADMIN, password: PASSWORD } })).json();
  const v2 = await request.post(`${API_URL}/v1/auth/mfa/verify`, { data: { mfa_token: t2.mfa_token, code: codes[1] } });
  expect(v2.status()).toBe(200);
  const blocked = await request.get(`${API_URL}/v1/edges`, { headers: { Authorization: `Bearer ${(await v2.json()).access_token}` } });
  expect(blocked.status()).toBe(403);                                                          // o token da API também
  expect(await blocked.json()).toEqual({ detail: "organization_suspended" });
  // reativar
  await page.goto("/plataforma/organizacoes");
  await page.getByTestId("org-linha").filter({ hasText: `${org} Renomeada` }).getByTestId("org-detalhe-link").click();
  await page.getByTestId("org-acao-estado").getByLabel(/Motivo/).fill("Voltou a pagar");
  await page.getByTestId("org-estado-enviar").click();
  await expect(page.getByTestId("org-flash")).toContainText("Organização reativada");
  await expect(page.getByTestId("org-estado")).toContainText("Ativa");
  await expect(page.getByTestId("org-encerramento")).toHaveCount(0);               // reativar cancelou o pedido e a seção some
  await up.goto("/");
  await expect(up.getByRole("heading", { name: "Visão Geral" })).toBeVisible();      // sem novo login
  await expect(up.getByTestId("org-suspensa-aviso")).toHaveCount(0);
  await ctx.close();
  // histórico: quem, o quê e o motivo
  const hist = page.getByTestId("org-historico");
  await expect(hist).toContainText("Suspensa");
  await expect(hist).toContainText("motivo: Contrato encerrado");
  await expect(hist).toContainText("onu_discovery: padrão → ligado");
  await expect(hist).toContainText("Renomeada");
  // (o histórico do detalhe ainda não traz os eventos platform.closure.*: o registro está em /plataforma/encerramentos)
  // registro permanente: a lista de encerramentos mostra o pedido cancelado, sem dado de pessoa
  await page.goto("/plataforma/organizacoes");
  await page.getByTestId("org-encerramentos-link").click();
  await expect(page.getByRole("heading", { name: "Encerramentos" })).toBeVisible();
  const linha = page.getByTestId("enc-linha").filter({ hasText: `${org} Renomeada` }).first();
  await expect(linha.getByTestId("enc-estado")).toHaveText("Pedido cancelado");
  expect(await ax("main")).toEqual([]);
  await expect(page.getByTestId("enc-lista")).not.toContainText("@");
});
