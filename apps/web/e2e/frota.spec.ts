import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { login } from "./helpers";

// Frota de OLTs (ADR-0041, PR2 parte A): cadastro e edição na nuvem. Nada é enviado à OLT e a credencial é só um NOME (nunca repetido na tela).
const SUFFIX = String(Date.now()).slice(-6);

test("frota: cria POP, cadastra OLT, edita POP/rótulo/credencial, sem a tela repetir o nome da credencial recusada", async ({ page }) => {
  await login(page);
  await page.goto("/rede");
  await page.getByTestId("rede-frota-link").click();
  await expect(page).toHaveURL(/\/rede\/frota$/);
  await expect(page.getByTestId("frota-cadastro")).toContainText("Nunca digite senha, chave ou endereço");
  // POP
  await page.getByTestId("frota-pops").getByLabel("Nome do POP").fill(`POP E2E ${SUFFIX}`);
  await page.getByTestId("frota-pops").getByLabel("Código (opcional)").fill(`E2E-${SUFFIX}`);
  await page.getByTestId("frota-criar-pop").click();
  await expect(page.getByTestId("frota-flash")).toContainText("POP criado");
  await expect(page.getByTestId("frota-pop").filter({ hasText: `POP E2E ${SUFFIX}` })).toHaveCount(1);
  // uma credencial que é um ENDEREÇO é recusada e o valor não volta na tela
  const form = page.getByTestId("frota-cadastro");
  await form.getByLabel("Nome da OLT").fill(`E2E-OLT-${SUFFIX}`);
  await form.getByLabel("Nome da credencial no Edge (opcional)").fill("10.9.8.7");
  await page.getByTestId("frota-cadastrar").click();
  await expect(page.getByTestId("frota-flash")).toContainText("fora do formato");
  await expect(page.locator("body")).not.toContainText("10.9.8.7");
  // cadastro válido
  await form.getByLabel("Nome da OLT").fill(`E2E-OLT-${SUFFIX}`);
  await form.getByLabel("POP").selectOption({ label: `POP E2E ${SUFFIX}` });
  await form.getByLabel("Rótulo (opcional)").fill("OLT de teste");
  await form.getByLabel("Nome da credencial no Edge (opcional)").fill(`olt-e2e-${SUFFIX}`);
  await page.getByTestId("frota-cadastrar").click();
  await expect(page.getByTestId("frota-flash")).toContainText("OLT cadastrada");
  const card = page.getByTestId("frota-olt").filter({ hasText: `E2E-OLT-${SUFFIX}` });
  await expect(card).toHaveCount(1);
  await expect(card).toContainText("Ainda não coletada");
  await expect(card).toContainText(`POP E2E ${SUFFIX}`);
  await expect(card).toContainText("credencial configurada");
  // o mesmo nome de novo é recusado
  await form.getByLabel("Nome da OLT").fill(`E2E-OLT-${SUFFIX}`);
  await page.getByTestId("frota-cadastrar").click();
  await expect(page.getByTestId("frota-flash")).toContainText("Já existe");
  // detalhe e edição
  await card.getByRole("link", { name: `E2E-OLT-${SUFFIX}` }).click();
  await expect(page.getByTestId("frota-detalhe")).toContainText("ainda não lido pelo Edge");
  await expect(page.getByTestId("frota-credencial")).toContainText("Informada");
  await expect(page.getByLabel("Substituir o nome da credencial no Edge")).toHaveValue("");               // o nome nunca volta da API
  await expect(page.locator("body")).not.toContainText(`olt-e2e-${SUFFIX}`);
  await page.getByLabel("Rótulo").fill("Rótulo novo");
  await page.getByTestId("frota-salvar").click();                                                         // sem tocar na credencial: ela continua informada
  await expect(page.getByTestId("frota-flash")).toContainText("OLT atualizada");
  await expect(page.getByLabel("Rótulo")).toHaveValue("Rótulo novo");
  await expect(page.getByTestId("frota-credencial")).toContainText("Informada");
  await page.getByLabel("Remover o nome da credencial").check();
  await page.getByTestId("frota-salvar").click();
  await expect(page.getByTestId("frota-credencial")).toContainText("Não informada");
  const res = await new AxeBuilder({ page: page as never }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  expect(res.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => v.id)).toEqual([]);
});

test("frota: parâmetros repetidos na URL e página inexistente não derrubam a tela", async ({ page }) => {
  await login(page);
  for (const qs of ["?ok=olt&ok=pop", "?erro=nome&erro=falha", "?ok[]=x&erro[a]=1", "?ok=%00"]) {
    const r = await page.goto(`/rede/frota${qs}`);
    expect(r?.status(), qs).toBe(200);
  }
  expect((await page.goto("/rede/frota/00000000-0000-0000-0000-000000000000"))?.status()).toBe(404);
  expect((await page.goto("/rede/frota/nao-e-uuid"))?.status()).toBe(404);
});
