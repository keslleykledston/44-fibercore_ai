import { expect, test } from "@playwright/test";
import { login } from "./helpers";

// Recuo dos ACS com a flag `acs_registry` DESLIGADA (ADR-0046 D2): ACS_FLAG_OFF=1 npx playwright test --project=recuo-acs
test("flag acs_registry desligada: sem atalho, /rede/acs é 404 e o BFF não cadastra nada", async ({ page }) => {
  test.skip(!process.env.ACS_FLAG_OFF, "rodar com ACS_FLAG_OFF=1 e a flag acs_registry desligada no provedor");
  await login(page);
  await page.goto("/rede");
  await expect(page.getByTestId("rede-acs-link")).toHaveCount(0);
  expect((await page.goto("/rede/acs"))?.status()).toBe(404);
  await page.goto("/rede");
  const origin = new URL(page.url()).origin;
  const r = await page.request.post(`${origin}/bff/acs`, { form: { name: "Sem flag", kind: "genieacs", edge_id: "11111111-1111-4111-8111-111111111111", enabled: "1" }, headers: { origin }, maxRedirects: 0 });
  expect([303, 307]).toContain(r.status());   // o BFF responde com redirecionamento e o erro é o da API (flag desligada): nada foi cadastrado
  expect(r.headers()["location"] ?? "").toContain("erro=desligado");
});
