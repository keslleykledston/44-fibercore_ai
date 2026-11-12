import { createECDH, randomBytes } from "node:crypto";
import { expect, test } from "@playwright/test";
import { login } from "./helpers";

// Recuo do centro de OLT com a flag `fleet_provision` DESLIGADA (a `fleet_manager` segue ligada; `fleet_secrets` pode estar ligada): FLEET_PROVISION_FLAG_OFF=1 npx playwright test --project=recuo-provisao
// Sem a flag o assistente e o botão "Cadastrar e continuar" somem e a entrega da conexão (kind olt_connection) responde 404 pelo BFF, como se não existisse.
/** Envelope só com o formato certo (versão 1, ponto P-256 real, nonce e tag): nunca é aberto por ninguém. */
function formatOnlyBlob(): string {
  const e = createECDH("prime256v1");
  e.generateKeys();
  return Buffer.concat([Buffer.from([1]), e.getPublicKey(), randomBytes(12), randomBytes(17)]).toString("base64url");
}

test("flag fleet_provision desligada: sem assistente, sem atalho e BFF 404 para a conexão", async ({ page }) => {
  test.skip(!process.env.FLEET_PROVISION_FLAG_OFF, "rodar com FLEET_PROVISION_FLAG_OFF=1 e a flag fleet_provision desligada no provedor");
  await login(page);
  await page.goto("/rede/frota");
  await expect(page.getByTestId("frota-cadastro")).toBeVisible();                       // a Frota segue disponível
  await expect(page.getByTestId("frota-cadastrar-continuar")).toHaveCount(0);
  await page.getByTestId("frota-olt").first().getByRole("link").first().click();
  await expect(page.getByTestId("frota-detalhe")).toBeVisible();
  await expect(page.getByTestId("frota-passos")).toHaveCount(0);
  await expect(page.getByTestId("conn-form")).toHaveCount(0);
  const id = page.url().match(/frota\/([0-9a-f-]{36})/)![1];
  const origin = new URL(page.url()).origin;
  const body = { delivery_id: "11111111-1111-4111-8111-111111111111", kind: "olt_connection", key_id: "0123456789abcdef", expires_at: Math.floor(Date.now() / 1000) + 600, sealed: formatOnlyBlob() };   // só o FORMATO certo: com `fleet_secrets` ligada a API valida o envelope antes de olhar a flag do kind
  expect((await page.request.post(`${origin}/bff/frota/olts/${id}/credenciais`, { data: body, headers: { origin } })).status()).toBe(404);
});

// Só a `fleet_provision` ligada (a `fleet_secrets` desligada): FLEET_PROVISION_ONLY=1 npx playwright test --project=recuo-provisao. O assistente aparece, mas nenhum campo de credencial existe e o passo 3 diz que o recurso está desligado.
test("só fleet_provision ligada: assistente com a chave do Edge e a conexão, sem campo de credencial", async ({ page }) => {
  test.skip(!process.env.FLEET_PROVISION_ONLY, "rodar com FLEET_PROVISION_ONLY=1, fleet_provision ligada e fleet_secrets desligada");
  await login(page);
  await page.goto("/rede/frota");
  await page.getByTestId("frota-olt").first().getByRole("link").first().click();
  await expect(page.getByTestId("frota-detalhe")).toBeVisible();
  await expect(page.getByTestId("frota-passos")).toBeVisible();
  await expect(page.getByTestId("passo-3")).toContainText("fleet_secrets");
  await expect(page.getByTestId("frota-credenciais")).toHaveCount(0);
  await expect(page.locator("input[type=password]")).toHaveCount(0);
  await expect(page.getByTestId("cred-envio")).toHaveCount(0);
});
