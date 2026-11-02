import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { login } from "./helpers";

// Fila de ONUs aguardando autorização (v2.5) na stack real com o seed SINTÉTICO: filtros, condições, origem e registro à mão. Nada é autorizado nem chega à OLT.
test("pendentes: condições, filtros, registro à mão e sem ação de autorizar", async ({ page }) => {
  await login(page);
  await page.goto("/rede");
  await page.getByTestId("rede-pendentes-link").first().click();
  await expect(page).toHaveURL(/\/rede\/pendentes/);
  await expect(page.getByTestId("pend-aviso")).toContainText("não existe nesta versão");
  const nova = page.getByTestId("pend-linha").filter({ hasText: "DEMOPEND0001" });
  await expect(nova).toContainText("Nova");
  await expect(nova).toContainText("não vale como leitura da OLT");
  await expect(page.getByTestId("pend-linha").filter({ hasText: "DEMOPEND0002" })).toContainText("Dado antigo");
  const conf = page.getByTestId("pend-linha").filter({ hasText: "DEMOA0000" });
  await expect(conf).toContainText("Conflito");
  await expect(conf).toContainText("já é uma ONU registrada");
  await expect(page.getByRole("button", { name: /autorizar/i })).toHaveCount(0);
  await page.getByTestId("pend-filtro-conflict").click();
  await expect(page.getByTestId("pend-linha")).toHaveCount(1);

  await page.goto("/rede/pendentes");
  await page.getByLabel("OLT").selectOption({ label: "OLT-DEMO-01" });
  await page.getByRole("button", { name: "Filtrar" }).click();
  await page.getByTestId("pend-registrar").locator("summary").click();
  await page.getByLabel(/Uma ONU por linha/).fill("0/1/5 DEMOPEND0003 zte\n0/1/5 DEMOPEND0004");
  await page.getByRole("button", { name: "Registrar", exact: true }).click();
  await expect(page.getByTestId("pend-flash")).toContainText("Avistamentos registrados");
  await expect(page.getByTestId("pend-linha").filter({ hasText: "DEMOPEND0003" })).toContainText("Nova");
  await page.getByTestId("pend-registrar").locator("summary").click();
  await page.getByLabel(/Uma ONU por linha/).fill("isto não é uma linha válida");
  await page.getByRole("button", { name: "Registrar", exact: true }).click();
  await expect(page.getByTestId("pend-flash")).toContainText("Linhas inválidas");
  const a11y = await new AxeBuilder({ page: page as never }).analyze();
  expect(a11y.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? ""))).toEqual([]);
});
