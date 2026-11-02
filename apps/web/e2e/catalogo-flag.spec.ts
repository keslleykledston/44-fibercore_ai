import { expect, test } from "@playwright/test";
import { login } from "./helpers";

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
