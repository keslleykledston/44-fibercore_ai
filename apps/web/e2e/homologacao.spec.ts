import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { login } from "./helpers";

// Homologação das OLTs (ADR-0041, PR6): o nível é calculado de evidência; sintético não conta; ninguém passa de L2.
test("homologação: três modelos, só a captura real chega a L1, nenhum acima de L2 e aviso de que firmware novo não herda nível", async ({ page }) => {
  await login(page);
  await page.goto("/rede/frota");
  await page.getByTestId("frota-homologacao-link").click();
  await expect(page).toHaveURL(/\/rede\/homologacao$/);
  await expect(page.getByTestId("hom-aviso")).toContainText("Firmware novo não herda nível");
  const eq = page.getByTestId("hom-equip");
  await expect(eq).toHaveCount(3);
  await expect(eq.filter({ hasText: "MA5608T" })).toHaveAttribute("data-level", "L1");
  await expect(eq.filter({ hasText: "MA5800" })).toHaveAttribute("data-level", "L0");
  await expect(eq.filter({ hasText: "C300" })).toHaveAttribute("data-level", "L0");
  for (const l of await eq.all()) expect(["L0", "L1", "L2"]).toContain(await l.getAttribute("data-level"));
  await expect(eq.filter({ hasText: "MA5608T" })).toContainText("PON sem ONU");   // a lacuna conhecida aparece como o que falta
  await expect(page.getByTestId("hom-legenda").getByRole("listitem")).toHaveCount(5);
});

test("homologação: os 22 testes da matriz mostram o tipo de evidência e a fixture sintética diz que não conta", async ({ page }) => {
  await login(page);
  await page.goto("/rede/homologacao");
  const ma = page.getByTestId("hom-equip").filter({ hasText: "MA5608T" });
  await expect(ma.locator("summary")).toContainText(/\d+ com captura real · \d+ só com teste automatizado/);   // captura real e teste automatizado nunca se somam
  await ma.locator("summary").click();
  await expect(ma.locator("tbody tr")).toHaveCount(22);
  await expect(ma).toContainText("Captura real");
  await expect(ma).toContainText("Sem evidência");
  const zte = page.getByTestId("hom-equip").filter({ hasText: "C300" });
  await zte.locator("summary").click();
  await expect(zte).toContainText("Fixture sintética (não conta)");
});

test("homologação: OLTs cadastradas com nível e leitura desatualizada marcada, e testes de conexão em 24 h", async ({ page }) => {
  await login(page);
  await page.goto("/rede/homologacao");
  await expect(page.getByTestId("hom-olt").first()).toBeVisible();
  await expect(page.getByTestId("hom-testes")).toBeVisible();
  await expect(page.getByTestId("hom-emdia").first()).toBeVisible();      // leitura recente: estado explícito
  await expect(page.getByTestId("hom-stale").first()).toBeVisible();      // e a velha ou nunca lida também
  const a11y = await new AxeBuilder({ page: page as never }).analyze();
  expect(a11y.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? ""))).toEqual([]);
});
