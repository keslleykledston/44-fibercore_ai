import { expect, test } from "@playwright/test";
import { login } from "./helpers";

// Recuo das credenciais da OLT com a flag `fleet_secrets` DESLIGADA (a `fleet_manager` segue ligada): FLEET_SECRETS_FLAG_OFF=1 npx playwright test --project=recuo-credenciais (com `fleet_secrets` e `fleet_provision` desligadas)
// ADR-0046: a chave do Edge também serve à `fleet_provision`; por isso este recuo exige as DUAS flags desligadas (com só a `fleet_provision` ligada o cartão aparece, mas só com a chave, e a rota da chave responde 200).
// Sem a flag o cartão não existe, o atalho do cadastro some e as rotas do BFF respondem 404 (como se não existissem).
test("flag fleet_secrets desligada: sem cartão, sem atalho no cadastro e BFF 404", async ({ page }) => {
  test.skip(!process.env.FLEET_SECRETS_FLAG_OFF, "rodar com FLEET_SECRETS_FLAG_OFF=1 e a flag fleet_secrets desligada no provedor");
  await login(page);
  await page.goto("/rede/frota");
  await expect(page.getByTestId("frota-cadastro")).toBeVisible();                       // a Frota em si segue disponível
  await expect(page.getByTestId("frota-cadastrar-credenciais")).toHaveCount(0);
  await page.getByTestId("frota-olt").first().getByRole("link").first().click();
  await expect(page.getByTestId("frota-detalhe")).toBeVisible();
  await expect(page.getByTestId("frota-credenciais")).toHaveCount(0);
  await expect(page.locator("input[type=password]")).toHaveCount(0);
  const id = page.url().match(/frota\/([0-9a-f-]{36})/)![1];
  const origin = new URL(page.url()).origin;
  const body = { delivery_id: "11111111-1111-4111-8111-111111111111", kind: "ssh_login", key_id: "0123456789abcdef", expires_at: Math.floor(Date.now() / 1000) + 600, sealed: "A".repeat(150) };
  expect((await page.request.post(`${origin}/bff/frota/olts/${id}/credenciais`, { data: body, headers: { origin } })).status()).toBe(404);
  expect((await page.request.get(`${origin}/bff/frota/olts/${id}/credenciais`, { headers: { "sec-fetch-site": "same-origin" } })).status()).toBe(404);
  const edgeId = "00000000-0000-4000-8000-000000000000";
  expect((await page.request.get(`${origin}/bff/frota/edges/${edgeId}/chave`, { headers: { "sec-fetch-site": "same-origin" } })).status()).toBe(404);
});
