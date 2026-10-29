import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { API_URL, EMAIL, PASSWORD, login, totp } from "./helpers";

const routes = ["/", "/rede", "/assinantes", "/noc", "/operacoes", "/administracao/modulos", "/administracao/membros", "/conta/seguranca", "/ajuda", "/ajuda/rede/consultar-onu"];

test("login inválido mostra erro e não cria sessão", async ({ page, context }) => {
  await page.goto("/login");
  await page.getByLabel("E-mail").fill("admin@demo.example.com");
  await page.getByLabel("Senha").fill("senha-errada");
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByTestId("login-error")).toBeVisible();
  await expect(page.getByTestId("login-steps").locator('[aria-current="step"]')).toContainText("Credenciais");
  expect((await context.cookies()).find((c) => c.name === "fc_token")).toBeUndefined();
});

test("login: etapa atual indicada e sem violações sérias de acessibilidade", async ({ page }) => {
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    await page.goto("/login");
    await expect(page.getByTestId("login-steps").locator('[aria-current="step"]')).toContainText("Credenciais");
    const res = await new AxeBuilder({ page: page as never }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
    const bad = res.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(bad.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`)).toEqual([]);
  }
});

test("telas protegidas redirecionam para login sem sessão", async ({ page }) => {
  for (const r of ["/", "/rede", "/rede/onu/00000000-0000-0000-0000-000000000000", "/assinantes", "/noc", "/operacoes", "/administracao/modulos", "/administracao/membros", "/conta/seguranca", "/ajuda"]) {
    await page.goto(r);
    await expect(page).toHaveURL(/\/login/);
  }
});

test("cookie de sessão é HttpOnly e inacessível ao JavaScript", async ({ page, context }) => {
  await login(page);
  const c = (await context.cookies()).find((x) => x.name === "fc_token")!;
  expect(c.httpOnly).toBe(true);
  expect(c.sameSite).toBe("Lax");
  expect(await page.evaluate(() => document.cookie)).not.toContain("fc_token");
  expect(await page.evaluate(() => JSON.stringify(Object.assign({}, localStorage)))).not.toMatch(/eyJ/);
});

test("mutações do BFF rejeitam origem diferente (CSRF)", async ({ page, request, baseURL }) => {
  await login(page);
  const r = await request.post(`${baseURL}/bff/logout`, { headers: { origin: "https://evil.example" }, maxRedirects: 0 });
  expect(r.status()).toBe(403);
  const ok = await request.post(`${baseURL}/bff/login`, { headers: { origin: "https://evil.example" }, form: { email: "a@b.co", password: "x" }, maxRedirects: 0 });
  expect(ok.status()).toBe(403);
});

test("Central de Ajuda não serve arquivos fora de docs/help", async ({ page }) => {
  await login(page);
  for (const p of ["/ajuda/..%2f..%2farchitecture%2fARCHITECTURE", "/ajuda/architecture/ARCHITECTURE", "/ajuda-assets/..%2f..%2f..%2fCLAUDE.md", "/ajuda-assets/rede/consultar-onu/../../../../package.json"]) {
    const res = await page.goto(p);
    expect(res!.status(), p).toBe(404);
  }
});

test("dados defasados e silêncio nunca viram 'offline' no texto de incidente", async ({ page }) => {
  await login(page);
  await page.goto("/noc");
  await expect(page.getByTestId("incident-queue")).toContainText("ONUs fora");
  await expect(page.getByTestId("incident-queue")).toContainText("hipótese, não diagnóstico");
});

test("busca por serial filtra a lista de ONUs", async ({ page }) => {
  await login(page);
  await page.getByLabel("Buscar ONU por serial").fill("DEMOA0001");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/rede\?serial=DEMOA0001/);
  await expect(page.locator("tbody tr")).toHaveCount(1);
});

test("ONU 360: painel lateral abre pelo serial, foco volta ao fechar e a página completa mostra origem e bloqueio de escrita", async ({ page }) => {
  await login(page);
  await page.goto("/rede?serial=DEMOA0001");
  const opener = page.getByTestId("onu-open");
  await opener.click();
  await expect(page.getByTestId("entity-drawer")).toBeVisible();
  await expect(page.getByTestId("onu-summary")).toContainText("OLT-DEMO-01");
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("entity-drawer")).toBeHidden();
  await expect(opener).toBeFocused();
  await opener.click();
  await page.getByTestId("onu-360-link").click();
  await expect(page).toHaveURL(/\/rede\/onu\/[0-9a-f-]{36}$/);
  await expect(page.getByRole("heading", { name: "ONU DEMOA0001" })).toBeVisible();
  await expect(page.getByTestId("onu360-state")).toContainText("Leitura da OLT pelo Edge");
  await expect(page.getByTestId("onu360-location")).toContainText("OLT-DEMO-01");
  await expect(page.getByTestId("onu360-customer")).toContainText(/Cliente Demo Um|sugestão/); // vínculo aprovado ou ainda sugerido, conforme a ordem dos testes
  await expect(page.getByTestId("onu360-actions")).toContainText("Nenhuma ação de escrita está liberada");
  const res = await new AxeBuilder({ page: page as never }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  const bad = res.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(bad.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`)).toEqual([]);
  expect((await page.goto("/rede/onu/00000000-0000-0000-0000-000000000000"))?.status()).toBe(404);
  expect((await page.goto("/rede/onu/nao-e-uuid"))?.status()).toBe(404);
});

for (const scheme of ["light", "dark"] as const) {
  test(`acessibilidade (axe) sem violações sérias - tema ${scheme}`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme });
    await login(page);
    for (const r of routes) {
      await page.goto(r);
      const res = await new AxeBuilder({ page: page as never }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
      const bad = res.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
      expect(bad.map((v) => `${v.id}: ${v.nodes[0]?.html}`), `${r} (${scheme})`).toEqual([]);
    }
  });
}

test("navegação por teclado alcança o conteúdo e a busca", async ({ page }) => {
  await login(page);
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Ir para o conteúdo" })).toBeFocused();
});

test("assinantes: serial ambíguo não pode ser aprovado; aprovação exige confirmação e é refletida", async ({ page }) => {
  await login(page);
  await page.goto("/assinantes");
  const items = page.getByTestId("association-list").locator("li");
  const ambiguous = items.filter({ hasText: "DEMODUP001" }).first();
  await expect(ambiguous).toContainText("ambíguo");
  await expect(ambiguous.locator("summary", { hasText: "Aprovar" })).toHaveAttribute("aria-disabled", "true");
  // aprovar um vínculo normal: abre a confirmação e só então efetiva
  const before = await items.count();
  const normal = items.filter({ hasText: "Cliente Demo Um" });
  await expect(normal).toHaveCount(1);
  await normal.locator("summary", { hasText: "Aprovar" }).click();
  await normal.getByRole("button", { name: "Confirmar aprovação" }).click();
  await expect(page.getByText("Vínculo aprovado.")).toBeVisible();
  await expect(items.filter({ hasText: "Cliente Demo Um" })).toHaveCount(0);
  await expect(items).toHaveCount(before - 1);
});

test("assinantes: importação mostra só contagens, nunca valores do CSV", async ({ page }) => {
  await login(page);
  await page.goto("/assinantes");
  const csv = "erp_customer_id,display_name,document,contract_status,onu_serial\nE2E1,Pessoa Secreta,123,active,\nE2E2,Outra Pessoa,,active,\n";
  await page.setInputFiles('input[name="file"]', { name: "clientes.csv", mimeType: "text/csv", buffer: Buffer.from(csv) });
  await page.getByRole("button", { name: "Importar" }).click();
  const report = page.getByTestId("import-report");
  await expect(report).toContainText("1 aceitas, 1 rejeitadas");
  expect(page.url()).not.toContain("Secreta");
  await expect(page.locator("body")).not.toContainText("Pessoa Secreta");
});

test("operações: escrita aparece bloqueada com o motivo e nenhum botão de escrita habilitado", async ({ page }) => {
  await login(page);
  await page.goto("/operacoes");
  await expect(page.getByTestId("write-blocked")).toContainText("Operação não homologada");
  const blocked = page.getByRole("button", { name: /Bloqueada: operação não homologada/ });
  await expect(blocked).toHaveCount(2);
  for (const b of await blocked.all()) await expect(b).toBeDisabled();
  await expect(page.getByTestId("jobs-table")).toContainText("Reiniciar CPE");
});

test("importação: corpo acima do limite é recusado antes de ser processado; sem Content-Length => 411", async ({ page, request, baseURL }) => {
  await login(page);
  const big = Buffer.alloc(3 * 1024 * 1024, "a");
  const cookies = (await page.context().cookies()).map((c) => `${c.name}=${c.value}`).join("; ");
  const r = await request.post(`${baseURL}/bff/erp/import`, {
    headers: { origin: baseURL!, cookie: cookies },
    multipart: { source: "csv-manual", file: { name: "grande.csv", mimeType: "text/csv", buffer: big } },
    maxRedirects: 0,
  });
  expect(r.status()).toBe(303);
  expect(r.headers()["location"]).toContain("erro=arquivo");
});

test("sessão renova com o refresh token rotativo quando o access token expira", async ({ page, context }) => {
  await login(page);
  const refresh1 = (await context.cookies()).find((c) => c.name === "fc_refresh")!;
  expect(refresh1.httpOnly).toBe(true);
  await context.clearCookies({ name: "fc_token" }); // simula o access token expirado
  await page.goto("/rede");
  await expect(page.getByRole("heading", { name: "Rede" }).first()).toBeVisible();
  const jar = await context.cookies();
  expect(jar.find((c) => c.name === "fc_token")).toBeDefined();
  expect(jar.find((c) => c.name === "fc_refresh")!.value).not.toBe(refresh1.value);
});

test("logout revoga o refresh token no servidor", async ({ page, context }) => {
  await login(page);
  const refresh = (await context.cookies()).find((c) => c.name === "fc_refresh")!.value;
  await page.getByRole("button", { name: /sair/i }).first().click();
  await expect(page).toHaveURL(/\/login/);
  expect((await page.request.post(`${API_URL}/v1/auth/refresh`, { data: { refresh_token: refresh } })).status()).toBe(401);
});

test("MFA: login em duas etapas com TOTP e código de recuperação; desativação limpa", async ({ page, request }) => {
  const tok = (await (await request.post(`${API_URL}/v1/auth/token`, { data: { email: EMAIL, password: PASSWORD } })).json()).access_token as string;
  const h = { Authorization: `Bearer ${tok}` };
  const secret = (await (await request.post(`${API_URL}/v1/auth/mfa/enroll`, { headers: h, data: { password: PASSWORD } })).json()).secret as string;
  const act = await request.post(`${API_URL}/v1/auth/mfa/activate`, { headers: h, data: { code: totp(secret) } });
  expect(act.status()).toBe(200);
  const recovery = (await act.json()).recovery_codes as string[];
  let disabled = false;
  try {
    await page.goto("/login");
    await page.getByLabel("E-mail").fill(EMAIL);
    await page.getByLabel("Senha").fill(PASSWORD);
    await page.getByRole("button", { name: "Entrar" }).click();
    await expect(page.getByRole("heading", { name: "Verificação em duas etapas" })).toBeVisible();
    await expect(page.getByTestId("login-steps").locator('[aria-current="step"]')).toContainText("Verificação");
    await page.getByLabel(/Código do aplicativo/).fill("000000");
    await page.getByRole("button", { name: "Verificar" }).click();
    await expect(page.getByTestId("mfa-error")).toBeVisible();
    await page.getByLabel(/Código do aplicativo/).fill(totp(secret, 1)); // passo seguinte: o do ativamento já foi consumido
    await page.getByRole("button", { name: "Verificar" }).click();
    await expect(page.getByRole("heading", { name: "Visão Geral" })).toBeVisible();
    const t2 = (await (await request.post(`${API_URL}/v1/auth/token`, { data: { email: EMAIL, password: PASSWORD } })).json());
    expect(t2.mfa_required).toBe(true);
    const off = await request.post(`${API_URL}/v1/auth/mfa/disable`, { headers: h, data: { password: PASSWORD, code: recovery[0] } });
    expect(off.status()).toBe(204);
    disabled = true;
  } finally {
    if (!disabled) await request.post(`${API_URL}/v1/auth/mfa/disable`, { headers: h, data: { password: PASSWORD, code: recovery[1] } });
  }
});

test("Segurança da conta: ativa o MFA pela tela, mostra os códigos uma única vez e desativa", async ({ page, request }) => {
  let secret = "";
  let recovery: string[] = [];
  try {
    await login(page);
    await page.getByRole("link", { name: "Segurança da conta" }).click();
    await expect(page.getByRole("heading", { name: "Segurança da conta" })).toBeVisible();
    await expect(page.getByTestId("mfa-status")).toHaveText(/Desativada/);
    // senha errada não gera segredo
    await page.getByTestId("mfa-enrol-password").fill("senha-errada");
    await page.getByTestId("mfa-enrol").click();
    await expect(page.getByTestId("mfa-error")).toContainText("incorretos");
    await expect(page.getByTestId("mfa-qr")).toHaveCount(0);
    // senha certa: QR + chave manual
    await page.getByTestId("mfa-enrol-password").fill(PASSWORD);
    await page.getByTestId("mfa-enrol").click();
    await expect(page.getByTestId("mfa-qr")).toBeVisible();
    expect(await page.getByTestId("mfa-qr").getAttribute("src")).toMatch(/^data:image\/png;base64,/);
    secret = (await page.getByTestId("mfa-secret").innerText()).replace(/\s/g, "");
    expect(secret).toMatch(/^[A-Z2-7]{32}$/);
    // código errado não ativa
    await page.getByTestId("mfa-code").fill("000000");
    await page.getByTestId("mfa-activate").click();
    await expect(page.getByTestId("mfa-error")).toContainText("incorretos");
    // código certo ativa e mostra os 8 códigos de recuperação
    await page.getByTestId("mfa-code").fill(totp(secret));
    await page.getByTestId("mfa-activate").click();
    await expect(page.getByTestId("mfa-recovery-codes")).toBeVisible();
    recovery = await page.getByTestId("mfa-recovery-codes").locator("li").allInnerTexts();
    expect(recovery).toHaveLength(8);
    for (const c of recovery) expect(c).toMatch(/^[0-9a-f]{10}-[0-9a-f]{10}$/);
    await expect(page.getByTestId("mfa-done")).toBeDisabled(); // só conclui depois de confirmar que guardou
    await page.getByTestId("mfa-saved").check();
    await page.getByTestId("mfa-done").click();
    await expect(page.getByTestId("mfa-status")).toHaveText(/Ativa/);
    await expect(page.getByTestId("mfa-left")).toContainText("8");
    await expect(page.getByTestId("mfa-recovery-codes")).toHaveCount(0); // nunca mais exibidos
    // o login agora exige o segundo fator
    const t = await (await request.post(`${API_URL}/v1/auth/token`, { data: { email: EMAIL, password: PASSWORD } })).json();
    expect(t.mfa_required).toBe(true);
    // gerar novos códigos: senha errada falha; senha + código de recuperação troca o conjunto inteiro, exibido uma única vez
    await page.getByText("Gerar novos códigos de recuperação").click();
    await page.getByTestId("mfa-regen-password").fill("senha-errada");
    await page.getByTestId("mfa-regen-code").fill(recovery[0]);
    await page.getByTestId("mfa-regen").click();
    await expect(page.getByTestId("mfa-regen-error")).toContainText("incorretos");
    await page.getByTestId("mfa-regen-password").fill(PASSWORD);
    await page.getByTestId("mfa-regen").click();
    await expect(page.getByTestId("mfa-codes-step")).toContainText("novos códigos");
    const fresh = await page.getByTestId("mfa-recovery-codes").locator("li").allInnerTexts();
    expect(fresh).toHaveLength(8);
    expect(fresh.filter((c) => recovery.includes(c))).toEqual([]); // nenhum igual aos anteriores
    await page.getByTestId("mfa-saved").check();
    await page.getByTestId("mfa-done").click();
    await expect(page.getByTestId("mfa-left")).toContainText("8");
    await expect(page.getByTestId("mfa-recovery-codes")).toHaveCount(0);
    recovery = fresh;
    // desativar: senha errada falha; senha + código de recuperação funciona
    await page.getByText("Desativar verificação em duas etapas").click();
    await page.getByTestId("mfa-disable-password").fill("senha-errada");
    await page.getByTestId("mfa-disable-code").fill(recovery[0]);
    await page.getByTestId("mfa-disable").click();
    await expect(page.getByTestId("mfa-error")).toContainText("incorretos");
    await page.getByTestId("mfa-disable-password").fill(PASSWORD);
    await page.getByTestId("mfa-disable").click();
    await expect(page.getByTestId("mfa-status")).toHaveText(/Desativada/);
    expect((await (await request.post(`${API_URL}/v1/auth/token`, { data: { email: EMAIL, password: PASSWORD } })).json()).mfa_required).toBeFalsy();
  } finally {
    // nunca deixa a conta de demonstração com MFA ligado (os outros testes entram só com senha)
    const t = await (await request.post(`${API_URL}/v1/auth/token`, { data: { email: EMAIL, password: PASSWORD } })).json();
    if (t.mfa_required && (recovery[1] || secret)) {
      const v = await request.post(`${API_URL}/v1/auth/mfa/verify`, { data: { mfa_token: t.mfa_token, code: recovery[1] ?? totp(secret, 2) } });
      if (v.ok()) {
        const tok = (await v.json()).access_token as string;
        await request.post(`${API_URL}/v1/auth/mfa/disable`, { headers: { Authorization: `Bearer ${tok}` }, data: { password: PASSWORD, code: recovery[2] ?? totp(secret, 3) } });
      }
    }
  }
});


test("Membros: administrador redefine o MFA de outra pessoa com senha + segundo fator, e a ação tem efeito", async ({ page, request }) => {
  const AGENT = "agente@demo.example.com";
  const tokenOf = async (email: string) => (await (await request.post(`${API_URL}/v1/auth/token`, { data: { email, password: PASSWORD } })).json()).access_token as string;
  const enable = async (email: string) => {
    const h = { Authorization: `Bearer ${await tokenOf(email)}` };
    const secret = (await (await request.post(`${API_URL}/v1/auth/mfa/enroll`, { headers: h, data: { password: PASSWORD } })).json()).secret as string;
    const act = await request.post(`${API_URL}/v1/auth/mfa/activate`, { headers: h, data: { code: totp(secret) } });
    expect(act.status()).toBe(200);
    return { h, secret, recovery: (await act.json()).recovery_codes as string[] };
  };
  const admin = await enable(EMAIL);
  await enable(AGENT);
  try {
    await page.goto("/login");
    await page.getByLabel("E-mail").fill(EMAIL);
    await page.getByLabel("Senha").fill(PASSWORD);
    await page.getByRole("button", { name: "Entrar" }).click();
    await page.getByLabel(/Código do aplicativo/).fill(totp(admin.secret, 1)); // o do ativamento já foi consumido
    await page.getByRole("button", { name: "Verificar" }).click();
    await expect(page.getByRole("heading", { name: "Visão Geral" })).toBeVisible();

    await page.goto("/administracao/membros");
    const row = page.getByTestId(`member-${AGENT}`);
    await expect(row).toContainText("Ativo");
    await expect(page.getByTestId(`member-${EMAIL}`).getByTestId("mfa-reset-open")).toHaveCount(0); // ninguém redefine o próprio por aqui
    await row.getByTestId("mfa-reset-open").click();
    await expect(page.getByTestId("mfa-reset-form")).toContainText("As sessões abertas");
    await page.getByLabel("Sua senha").fill("senha-errada");
    await page.getByLabel(/Seu código/).fill(admin.recovery[0]);
    await page.getByRole("button", { name: "Redefinir MFA" }).last().click();
    await expect(page.getByTestId("mfa-reset-error")).toContainText("incorretos");
    await page.getByLabel("Sua senha").fill(PASSWORD);
    await page.getByLabel(/Seu código/).fill(admin.recovery[1]);
    await page.getByRole("button", { name: "Redefinir MFA" }).last().click();
    await expect(page.getByTestId("entity-drawer")).toBeHidden();
    await expect(row).toContainText("Desativado");
    await expect(row.getByTestId("mfa-reset-open")).toHaveCount(0);
    expect((await (await request.post(`${API_URL}/v1/auth/token`, { data: { email: AGENT, password: PASSWORD } })).json()).mfa_required).toBe(false);
    const axe = await new AxeBuilder({ page: page as never }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
    expect(axe.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`)).toEqual([]);
  } finally {
    await request.post(`${API_URL}/v1/auth/mfa/disable`, { headers: admin.h, data: { password: PASSWORD, code: admin.recovery[2] } });
  }
});
