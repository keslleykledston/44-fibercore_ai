import { expect, test } from "@playwright/test";
import { login } from "./helpers";

// Recuo da Frota de OLTs com a flag `fleet_manager` DESLIGADA: FLEET_FLAG_OFF=1 npx playwright test --project=recuo-frota
test("flag fleet_manager desligada: sem atalho e /rede/frota é 404", async ({ page }) => {
  test.skip(!process.env.FLEET_FLAG_OFF, "rodar com FLEET_FLAG_OFF=1 e a flag fleet_manager desligada no provedor");
  await login(page);
  await page.goto("/rede");
  await expect(page.getByTestId("rede-frota-link")).toHaveCount(0);
  expect((await page.goto("/rede/frota"))?.status()).toBe(404);
});
