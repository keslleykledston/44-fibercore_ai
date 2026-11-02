import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { login } from "./helpers";

// Profile Studio (ADR-0040) na stack real com o seed SINTÉTICO: importa à mão, cria rascunho, edita (Assistido e Especialista), compara e simula. Nada chega à OLT.
test("perfis: do instantâneo ao dry-run, sem escrita e sem violações de acessibilidade", async ({ page }) => {
  await login(page);
  await page.goto("/rede");
  await page.getByTestId("rede-perfis-link").first().click();
  await expect(page).toHaveURL(/\/rede\/perfis/);
  await page.getByTestId("perfis-olt").filter({ hasText: "OLT-DEMO-01" }).click();
  await expect(page.getByTestId("perfis-cert")).toContainText("certificada");
  const linhas = page.getByTestId("perfis-linha");
  await expect(linhas).toHaveCount(2);
  await expect(linhas.first()).toContainText("não vale como leitura da OLT");   // importação manual nunca é autoritativa

  // importa mais um perfil à mão
  await page.getByTestId("perfis-importar").locator("summary").click();
  await page.getByLabel("Nome/ID na OLT").fill("DEMO-LINHA-E2E");
  await page.getByLabel("Placa PON").fill("GPBD-DEMO");
  await page.getByLabel("Campos do perfil (JSON tipado)").fill('{"dba_type":"type4","maximum_kbps":250000,"customer_vlan":100}');
  await page.getByRole("button", { name: "Importar instantâneo" }).click();
  await expect(page.getByTestId("perfis-flash")).toContainText("Perfil importado");
  await expect(page.getByTestId("perfis-linha")).toHaveCount(3);

  // um campo proibido (comando de CLI) é recusado
  await page.getByTestId("perfis-importar").locator("summary").click();
  await page.getByLabel("Nome/ID na OLT").fill("DEMO-PROIBIDO");
  await page.getByLabel("Placa PON").fill("GPBD-DEMO");
  await page.getByLabel("Campos do perfil (JSON tipado)").fill('{"dba_type":"type4","raw_cli":"undo everything"}');
  await page.getByRole("button", { name: "Importar instantâneo" }).click();
  await expect(page.getByTestId("perfis-flash")).toContainText("Dados inválidos");
  await expect(page.getByTestId("perfis-linha")).toHaveCount(3);

  // cria o rascunho a partir do perfil de 500M
  const alvo = page.getByTestId("perfis-linha").filter({ hasText: "DEMO-LINHA-500M" });
  await alvo.locator("summary").click();
  await alvo.getByLabel("Nome do rascunho").fill("Rascunho e2e");
  await alvo.getByLabel("Motivo").fill("teste e2e");
  await alvo.getByRole("button", { name: "Criar cópia editável" }).click();
  await expect(page).toHaveURL(/\/rede\/perfis\/[0-9a-f-]{36}$/);
  await expect(page.getByTestId("perfis-aviso")).toContainText("não alteram a OLT");

  // Assistido: sobe a banda máxima
  await page.getByLabel("Banda máxima (kbps)").fill("750000");
  await page.getByRole("button", { name: "Salvar rascunho" }).click();
  await expect(page.getByTestId("perfis-flash")).toContainText("Rascunho salvo");

  // Especialista: JSON com campo proibido é recusado; o válido salva
  await page.getByTestId("perfis-aba-especialista").click();
  await page.getByTestId("perfis-json").fill('{"maximum_kbps":750000,"command":"x"}');
  await page.getByRole("button", { name: "Salvar rascunho" }).click();
  await expect(page.getByTestId("perfis-flash")).toContainText("Não salvei");
  await page.getByTestId("perfis-aba-especialista").click();
  await page.getByTestId("perfis-json").fill('{"dba_type":"type4","maximum_kbps":750000,"customer_vlan":100,"tagging":"tagged","shaping_owner":"olt"}');
  await page.getByRole("button", { name: "Salvar rascunho" }).click();
  await expect(page.getByTestId("perfis-flash")).toContainText("Rascunho salvo");

  // comparação semântica: a banda muda; o instantâneo manual NÃO deixa afirmar equivalência
  const opt = await page.locator('select[name="comparar"] option', { hasText: "DEMO-LINHA-500M" }).getAttribute("value");
  await page.getByLabel("Perfil observado").selectOption(opt!);
  await page.getByRole("button", { name: "Comparar", exact: true }).click();
  const diff = page.getByTestId("perfis-diff");
  await expect(diff).toBeVisible();
  await expect(diff.getByTestId("perfis-equivalente")).toContainText("Não dá para afirmar");
  await expect(diff.getByTestId("perfis-bloqueios")).toContainText("importado à mão");
  await expect(diff.getByTestId("perfis-diff-linha").filter({ hasText: "Banda máxima" })).toContainText("Muda");

  // dry-run: zero escrita, não executável, reproduzível
  await page.getByTestId("perfis-simular").click();
  await expect(page.getByTestId("perfis-resultado")).toBeVisible();
  await expect(page.getByTestId("perfis-sem-escrita")).toContainText("Escritas na OLT: 0");
  await expect(page.getByTestId("perfis-sem-escrita")).toContainText("não executável");
  await expect(page.getByTestId("perfis-sem-escrita")).toContainText("reproduzível");
  await expect(page.getByTestId("perfis-plano")).toHaveCount(1);
  const a11y = await new AxeBuilder({ page: page as never }).analyze();
  expect(a11y.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? ""))).toEqual([]);
});

test("perfis: duas abas editando o mesmo rascunho — a segunda é recusada (If-Match), nada é sobrescrito", async ({ browser }) => {
  const ctx = await browser.newContext(); const a = await ctx.newPage(); const b = await ctx.newPage();
  await login(a);
  await a.goto("/rede/perfis");
  await a.getByTestId("perfis-rascunho").first().click();
  await a.waitForURL(/\/rede\/perfis\/[0-9a-f-]{36}/);
  await b.goto(a.url());
  await a.getByLabel("Banda máxima (kbps)").fill("111000");
  await b.getByLabel("Banda máxima (kbps)").fill("222000");
  await a.getByRole("button", { name: "Salvar rascunho" }).click();
  await expect(a.getByTestId("perfis-flash")).toContainText("Rascunho salvo");
  await b.getByRole("button", { name: "Salvar rascunho" }).click();
  await expect(b.getByTestId("perfis-flash")).toContainText("Outra pessoa salvou");
  await b.reload();
  await expect(b.getByLabel("Banda máxima (kbps)")).toHaveValue("111000");
  await ctx.close();
});
