import { expect, test } from "@playwright/test";
import { login } from "./helpers";

// Recuo: com a flag `profile_studio` DESLIGADA no provedor a tela não existe e o atalho some. Só roda com PERFIS_FLAG_OFF=1.
test("flag profile_studio desligada: sem atalho na Rede e /rede/perfis é 404", async ({ page }) => {
  test.skip(!process.env.PERFIS_FLAG_OFF, "rodar com PERFIS_FLAG_OFF=1 e a flag profile_studio desligada no provedor");
  await login(page);
  await page.goto("/rede");
  await expect(page.getByTestId("rede-perfis-link")).toHaveCount(0);
  const r = await page.goto("/rede/perfis");
  expect(r?.status()).toBe(404);
});
