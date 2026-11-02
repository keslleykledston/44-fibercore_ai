import { expect, test } from "@playwright/test";
import { API_URL, EMAIL, login, PASSWORD } from "./helpers";

// Prova do recuo da aba Histórico da Visão 360 do assinante: ela usa a flag `onu_quick_inspector` (a mesma rota do painel da Rede). Só roda com a flag desligada no provedor:
// ASSINANTE_HISTORICO_FLAG_OFF=1. Com ela desligada a aba não existe e uma URL `?aba=historico` cai na primeira aba disponível, sem pedir o histórico.
test("flag onu_quick_inspector desligada: sem aba Histórico na Visão 360 do assinante e a URL direta cai na Conexão", async ({ page, request }) => {
  test.skip(!process.env.ASSINANTE_HISTORICO_FLAG_OFF, "rodar com ASSINANTE_HISTORICO_FLAG_OFF=1 e a flag onu_quick_inspector desligada no provedor");
  const tok = (await (await request.post(`${API_URL}/v1/auth/token`, { data: { email: EMAIL, password: PASSWORD } })).json()).access_token as string;
  const h = { Authorization: `Bearer ${tok}` };
  const assoc = (await (await request.get(`${API_URL}/v1/associations?status=suggested&limit=200`, { headers: h })).json()) as { id: string; customer_name: string }[];
  const a = assoc.find((x) => x.customer_name === "Cliente Demo Três");
  if (a) expect((await request.post(`${API_URL}/v1/associations/${a.id}/approve`, { headers: h })).status()).toBe(200);
  await login(page);
  await page.goto("/assinantes");
  await page.getByLabel("Buscar cliente pelo nome").fill("demo tr");
  await page.getByRole("button", { name: "Buscar", exact: true }).click();
  await page.getByTestId("customer-list").getByRole("link", { name: /Cliente Demo Três/ }).click();
  await expect(page).toHaveURL(/\/assinantes\/[0-9a-f-]{36}$/);
  await expect(page.getByTestId("tab-conexao")).toBeVisible();
  await expect(page.getByTestId("tab-historico")).toHaveCount(0);
  const base = new URL(page.url()).pathname;
  const asked: string[] = [];
  page.on("request", (r) => { if (r.url().includes("/history")) asked.push(r.url()); });
  await page.goto(`${base}?aba=historico`);
  await expect(page.getByTestId("sub-historico")).toHaveCount(0);
  await expect(page.getByTestId("sub-conexao")).toBeVisible();                                   // caiu na primeira aba disponível
  expect(asked).toEqual([]);                                                                     // e não pediu o histórico
});
