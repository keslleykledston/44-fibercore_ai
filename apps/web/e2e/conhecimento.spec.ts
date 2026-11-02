import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { login } from "./helpers";

// Base de conhecimento (ADR-0041, PR5): referência somente leitura. Nada é executável nem prova de suporte.
test("conhecimento: aviso 'documentado não é verificado', seis seções e nenhum controle de execução", async ({ page }) => {
  await login(page);
  await page.goto("/rede/frota");
  await page.getByTestId("frota-conhecimento-link").click();
  await expect(page).toHaveURL(/\/rede\/conhecimento$/);
  await expect(page.getByTestId("kb-aviso")).toContainText("Documentado não é verificado");
  await expect(page.getByTestId("kb-secoes").getByRole("link")).toHaveCount(6);
  await expect(page.getByTestId("kb-fonte")).toHaveCount(25);
  for (const a of await page.getByTestId("kb-fonte").getByRole("link").all()) {
    await expect(a).toHaveAttribute("href", /^https:\/\//);
    await expect(a).toHaveAttribute("rel", /noopener/);
  }
  await page.getByRole("link", { name: "Consultas documentadas" }).click();
  await expect(page.getByTestId("kb-comando")).toHaveCount(19);
  await expect(page.getByTestId("kb-comandos")).toContainText("não executável");
  await expect(page.getByRole("button", { name: /executar|enviar|aplicar|rodar/i })).toHaveCount(0);
  // filtro por fabricante
  await page.getByLabel("Fabricante").selectOption("huawei");
  await page.getByRole("button", { name: "Filtrar" }).click();
  await expect(page.getByTestId("kb-comando")).toHaveCount(4);
  const a11y = await new AxeBuilder({ page: page as never }).analyze();
  expect(a11y.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? ""))).toEqual([]);
});

test("conhecimento: runbooks, intenções (só desenho), receitas não homologadas e matriz sem apply", async ({ page }) => {
  await login(page);
  await page.goto("/rede/conhecimento?secao=runbooks");
  await expect(page.getByTestId("kb-runbook")).toHaveCount(8);
  await page.goto("/rede/conhecimento?secao=intents");
  await expect(page.getByTestId("kb-intent")).toHaveCount(6);
  await expect(page.getByTestId("kb-intents")).toContainText("apenas desenho");
  await page.goto("/rede/conhecimento?secao=receitas");
  await expect(page.getByTestId("kb-receita")).toHaveCount(8);
  for (const r of await page.getByTestId("kb-receita").all()) await expect(r).toContainText(/Exemplo documentado, não homologado|Só pesquisa|verificar no local/);
  await page.goto("/rede/conhecimento?secao=homologacao");
  await expect(page.getByTestId("kb-homologacao")).toContainText("nenhum fabricante certificado");
  const linhas = page.getByTestId("kb-matriz-linha");
  await expect(linhas).toHaveCount(8);
  for (const l of await linhas.all()) await expect(l).toContainText("blocked_by_default");
});

test("conhecimento: seção e fabricante estranhos na URL não derrubam a página", async ({ page }) => {
  await login(page);
  const r = await page.goto("/rede/conhecimento?secao=x&secao=y&vendor=%3Cscript%3E&vendor=a");
  expect(r?.status()).toBe(200);
  await expect(page.getByTestId("kb-fonte")).toHaveCount(25);   // seção desconhecida cai na primeira; fabricante desconhecido não filtra
});
