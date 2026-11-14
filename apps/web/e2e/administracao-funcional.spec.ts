import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { login } from "./helpers";

// Administração da organização (ADR-0048 a 0051) contra a stack REAL. A stack do e2e não tem SMTP nem chave de webhook: o e-mail não é oferecido e os webhooks aparecem como indisponíveis.
// Cada teste devolve o estado que mudou (política, escopo, token).
const AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"];

test("Equipe: sem SMTP configurado a caixa 'enviar por e-mail' não é oferecida e o selo de escopo aparece", async ({ page }) => {
  await login(page);
  await page.goto("/administracao/equipe");
  await expect(page.getByTestId("team-ready")).toBeVisible();
  await expect(page.getByTestId("person-agente@demo.example.com").getByTestId("person-scope")).toContainText("Escopo: provedor inteiro");
  await page.getByTestId("invite-open").click();
  const dlg = page.locator("dialog[open]");
  await expect(dlg.getByTestId("invite-form")).toBeVisible();
  await expect(dlg.getByTestId("invite-email-option")).toHaveCount(0);
});

test("Segurança da organização: o piso aparece travado, a política só acrescenta, pede confirmação e se desfaz", async ({ page }) => {
  await login(page);
  await page.goto("/administracao/equipe");
  await expect(page.getByRole("link", { name: "Segurança da organização" })).toBeVisible();
  await page.getByRole("link", { name: "Segurança da organização" }).click();
  await expect(page.getByTestId("policy-ready")).toBeVisible();
  await expect(page.getByTestId("policy-floor")).toContainText("Gestor de acesso");
  await expect(page.getByTestId("policy-role-access_manager").getByRole("checkbox")).toBeDisabled();   // o piso não sai
  const axe = await new AxeBuilder({ page: page as never }).withTags(AXE_TAGS).analyze();
  expect(axe.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);
  const noc = page.getByTestId("policy-role-noc_n1").getByRole("checkbox");
  await noc.check();
  await page.getByTestId("policy-save").click();
  await expect(page.getByTestId("policy-confirm")).toContainText("Confirmar a nova política?");
  await page.getByTestId("policy-confirm-yes").click();
  await expect(page.getByTestId("policy-done")).toContainText("Política salva");
  await page.reload();
  await expect(page.getByTestId("policy-role-noc_n1").getByRole("checkbox")).toBeChecked();
  await page.getByTestId("policy-role-noc_n1").getByRole("checkbox").uncheck();
  await page.getByTestId("policy-save").click();
  await page.getByTestId("policy-confirm-yes").click();
  await expect(page.getByTestId("policy-done")).toBeVisible();
  await page.reload();
  await expect(page.getByTestId("policy-role-noc_n1").getByRole("checkbox")).not.toBeChecked();
});

test("Escopo: o administrador restringe uma pessoa a uma OLT, o selo muda, e remove a restrição", async ({ page }) => {
  await login(page);
  await page.goto("/administracao/equipe");
  const row = page.getByTestId("person-agente@demo.example.com");
  await row.getByTestId("scope-open").click();
  const dlg = page.locator("dialog[open]");
  await expect(dlg.getByTestId("scope-panel")).toContainText("só LÊ a rede");
  await expect(dlg.getByTestId("scope-form")).toBeVisible();
  await expect(dlg.getByTestId("scope-save")).toBeDisabled();                                   // vazio não salva
  await dlg.getByRole("group", { name: "OLTs" }).getByRole("checkbox").first().check();
  await dlg.getByTestId("scope-save").click();
  await expect(page.getByTestId("person-agente@demo.example.com").getByTestId("person-scope")).toContainText("Restrito: 1 OLT");
  await page.getByTestId("person-agente@demo.example.com").getByTestId("scope-open").click();
  await page.locator("dialog[open]").getByTestId("scope-clear").click();
  await expect(page.getByTestId("person-agente@demo.example.com").getByTestId("person-scope")).toContainText("Escopo: provedor inteiro");
});

test("Tokens de API: o token aparece uma vez, some ao recarregar, a lista mostra só o prefixo e a revogação pede confirmação", async ({ page, request }) => {
  const name = `BI do NOC ${Date.now()}`;
  await login(page);
  await page.goto("/administracao/integracoes");
  await expect(page.getByTestId("tokens-readonly")).toContainText("Só leitura");
  const axe = await new AxeBuilder({ page: page as never }).withTags(AXE_TAGS).analyze();
  expect(axe.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);
  await expect(page.getByTestId("token-create")).toBeDisabled();                                 // sem permissão escolhida não cria
  await page.getByTestId("token-form").getByLabel(/^Nome/).fill(name);
  await page.getByTestId("token-perm-inventory:read").getByRole("checkbox").check();
  await page.getByTestId("token-create").click();
  const token = await page.getByTestId("secret-value-text").inputValue();
  expect(token).toMatch(/^fcat_[A-Za-z0-9]{8}_[A-Za-z0-9_-]{43}$/);
  await page.reload();
  await expect(page.getByTestId("secret-value")).toHaveCount(0);                                 // nunca mais
  const item = page.getByTestId(`token-${name}`);
  await expect(item).toContainText(`fcat_${token.slice(5, 13)}…`);
  expect(await item.innerText()).not.toContain(token.slice(14));
  // o token funciona na API (leitura) e não passa de leitura
  const api = process.env.E2E_API_URL ?? "http://127.0.0.1:18420";
  expect((await request.get(`${api}/v1/olts`, { headers: { Authorization: `Bearer ${token}` } })).status()).toBe(200);
  expect((await request.get(`${api}/v1/members`, { headers: { Authorization: `Bearer ${token}` } })).status()).toBe(403);
  await item.getByTestId("token-revoke").click();
  await expect(item).toContainText("Revogar agora?");
  await item.getByTestId("token-revoke-yes").click();
  await expect(page.getByTestId(`token-${name}`)).toContainText("Revogado");
  expect((await request.get(`${api}/v1/olts`, { headers: { Authorization: `Bearer ${token}` } })).status()).toBe(401);
});

test("Webhooks: sem a chave do servidor a tela explica e não deixa criar; a assinatura é explicada", async ({ page }) => {
  await login(page);
  await page.goto("/administracao/integracoes?aba=webhooks");
  await expect(page.getByTestId("webhooks-unavailable")).toContainText("chave de cifra");
  await expect(page.getByTestId("webhook-create")).toBeDisabled();
  await page.getByTestId("webhook-form").getByLabel(/^Nome/).fill("NOC");
  await page.getByTestId("webhook-form").getByLabel(/^URL/).fill("http://hooks.exemplo.com.br/x");
  await page.getByTestId("webhook-event-incident.opened").getByRole("checkbox").check();
  await expect(page.getByTestId("webhook-create")).toBeDisabled();                               // continua desabilitado: servidor sem chave
  await page.getByTestId("signature-help").locator("summary").click();
  await expect(page.getByTestId("signature-help")).toContainText("X-FiberCore-Signature");
  const axe = await new AxeBuilder({ page: page as never }).withTags(AXE_TAGS).analyze();
  expect(axe.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);
});
