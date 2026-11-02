import { expect, test } from "@playwright/test";
import { API_URL, EMAIL, login, PASSWORD } from "./helpers";

// Recuo da ONU 360° enxuta: sem a flag `onu_quick_inspector` não há identificação no alto e a tela é a de antes, com as linhas que a versão nova deixa de repetir.
// Só roda com a flag desligada no provedor: ONU360_FLAG_OFF=1 npx playwright test --project=recuo-onu360
test("flag onu_quick_inspector desligada: ONU 360° mantém Status, Rx, idade, OLT e PON nos cartões", async ({ page, request }) => {
  test.skip(!process.env.ONU360_FLAG_OFF, "rodar com ONU360_FLAG_OFF=1 e a flag onu_quick_inspector desligada no provedor");
  const tok = (await (await request.post(`${API_URL}/v1/auth/token`, { data: { email: EMAIL, password: PASSWORD } })).json()).access_token as string;
  const onus = (await (await request.get(`${API_URL}/v1/onus?limit=1`, { headers: { Authorization: `Bearer ${tok}` } })).json()) as { items?: { id: string }[]; onus?: { id: string }[] } | { id: string }[];
  const id = (Array.isArray(onus) ? onus : (onus.items ?? onus.onus ?? []))[0]?.id;
  expect(id).toBeTruthy();
  await login(page);
  await page.goto(`/rede/onu/${id}`);
  await expect(page.getByTestId("onu360-ready")).toBeVisible();
  await expect(page.getByTestId("onu360-identity")).toHaveCount(0);
  await expect(page.getByTestId("onu360-faceplate")).toHaveCount(0);
  const state = page.getByTestId("onu360-state");
  for (const k of ["Status", "Potência recebida (Rx)", "Último dado"]) await expect(state).toContainText(k);
  const loc = page.getByTestId("onu360-location");
  for (const k of ["OLT", "Equipamento", "PON"]) await expect(loc).toContainText(k);
});
