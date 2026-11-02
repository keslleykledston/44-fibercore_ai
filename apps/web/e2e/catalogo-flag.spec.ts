import { expect, test } from "@playwright/test";
import { login, onuWithConfirmedCpe } from "./helpers";

// Recuo do catálogo de equipamentos com a flag `device_assets` DESLIGADA: DEVICE_ASSETS_FLAG_OFF=1 npx playwright test --project=recuo-catalogo
test("flag device_assets desligada: sem atalho, sem miniaturas e /rede/catalogo é 404", async ({ page }) => {
  test.skip(!process.env.DEVICE_ASSETS_FLAG_OFF, "rodar com DEVICE_ASSETS_FLAG_OFF=1 e a flag device_assets desligada no provedor");
  await login(page);
  await page.goto("/rede");
  await expect(page.getByTestId("rede-catalogo-link")).toHaveCount(0);
  await expect(page.getByTestId("device-thumb")).toHaveCount(0);
  const r = await page.goto("/rede/catalogo");
  expect(r?.status()).toBe(404);
});

test("flag device_assets desligada: a sidebar do aparelho segue com o desenho neutro de antes, sem arte de modelo", async ({ page, request }) => {
  test.skip(!process.env.DEVICE_ASSETS_FLAG_OFF, "rodar com DEVICE_ASSETS_FLAG_OFF=1 e a flag device_assets desligada no provedor");
  const onu = await onuWithConfirmedCpe(request);
  await login(page);
  await page.goto(`/rede/onu/${onu}`);
  await page.getByTestId("ont-sidebar-open").click();
  await expect(page.getByTestId("ont-sidebar")).toBeVisible();
  await expect(page.getByTestId("ont-thumbnail")).toBeVisible();
  await expect(page.getByTestId("ont-sidebar-model-thumb")).toHaveCount(0);
  await expect(page.getByTestId("device-thumb")).toHaveCount(0);
});
