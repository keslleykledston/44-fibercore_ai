import { expect, test } from "@playwright/test";
import { login } from "./helpers";

// Recuo: com a flag `onu_discovery` DESLIGADA no provedor a tela não existe e o atalho some. Só roda com PENDENTES_FLAG_OFF=1.
test("flag onu_discovery desligada: sem atalho na Rede e /rede/pendentes é 404", async ({ page }) => {
  test.skip(!process.env.PENDENTES_FLAG_OFF, "rodar com PENDENTES_FLAG_OFF=1 e a flag onu_discovery desligada no provedor");
  await login(page);
  await page.goto("/rede");
  await expect(page.getByTestId("rede-pendentes-link")).toHaveCount(0);
  const r = await page.goto("/rede/pendentes");
  expect(r?.status()).toBe(404);
});
