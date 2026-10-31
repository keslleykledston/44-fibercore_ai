import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext } from "@playwright/test";
import { API_URL, EMAIL, login, PASSWORD } from "./helpers";

/** Confirma (idempotente) o vínculo ONU↔CPE de DEMOA0002 e devolve o id da ONU. A configuração do aparelho é o perfil SINTÉTICO do seed (rotulado como tal). */
async function onuWithConfirmedCpe(request: APIRequest) {
  const tok = (await (await request.post(`${API_URL}/v1/auth/token`, { data: { email: EMAIL, password: PASSWORD } })).json()).access_token as string;
  const h = { Authorization: `Bearer ${tok}` };
  expect((await request.post(`${API_URL}/v1/onu-cpe-links/suggest`, { headers: h })).status()).toBe(201);
  const links = (await (await request.get(`${API_URL}/v1/onu-cpe-links?status=suggested&limit=200`, { headers: h })).json()) as { id: string; onu: { id: string; serial: string } }[];
  const mine = links.find((l) => l.onu.serial === "DEMOA0002");
  if (mine) expect((await request.post(`${API_URL}/v1/onu-cpe-links/${mine.id}/confirm`, { headers: h })).status()).toBe(200);
  const onus = (await (await request.get(`${API_URL}/v1/onus?serial=DEMOA0002`, { headers: h })).json()) as { id: string; serial: string }[];
  return onus.find((o) => o.serial === "DEMOA0002")!.id;
}
type APIRequest = APIRequestContext;

test("configuração do aparelho: sidebar não modal, somente leitura, com instâncias reais, óptica e dados sintéticos rotulados", async ({ page, request }) => {
  const onu = await onuWithConfirmedCpe(request);
  await login(page);
  await page.goto(`/rede/onu/${onu}`);
  await page.getByTestId("ont-sidebar-open").click();
  const bar = page.getByTestId("ont-sidebar");
  await expect(bar).toBeVisible();
  await expect(page.getByTestId("ont-thumbnail")).toBeVisible();
  await expect(page.getByTestId("ont-synthetic")).toContainText("sintéticos");
  await expect(page.getByTestId("ont-sidebar-state")).toContainText("Leitura recente");
  await expect(bar).toContainText("Somente leitura");
  // não é modal: a página por trás segue acessível
  await expect(page.getByTestId("onu360-state")).toBeVisible();
  expect(await page.evaluate(() => document.querySelector("dialog[open]"))).toBeNull();
  // Resumo: óptica somente leitura, sem controle de edição
  const optical = page.getByTestId("ont-optical");
  await expect(optical).toContainText("Potência recebida");
  await expect(optical.locator("input")).toHaveCount(2);
  for (const i of await optical.locator("input").all()) await expect(i).toHaveAttribute("readonly", "");
  await expect(page.getByLabel("Potência recebida")).toHaveValue("-19.4 dBm");
  // Wi-Fi: duas redes reais, trocar a rede troca os campos; a senha nunca aparece
  await page.getByRole("tab", { name: "Wi-Fi" }).click();
  await expect(page.getByLabel("Nome da rede")).toHaveValue("Rede_Demo_2G");
  await page.getByLabel("Rede", { exact: true }).selectOption({ label: "Rede 5 GHz" });
  await expect(page.getByLabel("Nome da rede")).toHaveValue("Rede_Demo_5G");
  await expect(page.getByLabel("Senha definida")).toHaveValue("definida");
  await expect(bar).not.toContainText(/senha[:=]/i);
  await page.getByRole("tab", { name: "LAN" }).click();
  await expect(page.getByLabel("Endereço IPv4 da LAN")).toHaveValue("192.168.1.1");
  await page.getByRole("tab", { name: "WAN" }).click();
  await expect(page.getByLabel("VLAN")).toHaveValue("100");
  for (const i of await bar.locator("input").all()) await expect(i).toHaveAttribute("readonly", "");
  await expect(bar.getByRole("button", { name: /salvar|aplicar|enviar|pré-visualizar/i })).toHaveCount(0);   // nenhum botão de escrita nesta entrega
  const a11y = await new AxeBuilder({ page: page as never }).include("[data-testid=ont-sidebar]").analyze();
  expect(a11y.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? ""))).toEqual([]);
  await page.keyboard.press("Escape");
  await expect(bar).toBeHidden();
  await expect(page.getByTestId("ont-sidebar-open")).toBeFocused();
});

test("configuração do aparelho: no celular o painel cobre a tela sem rolagem lateral", async ({ page, request }) => {
  const onu = await onuWithConfirmedCpe(request);
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page);
  await page.goto(`/rede/onu/${onu}`);
  await page.getByTestId("ont-sidebar-open").click();
  await expect(page.getByTestId("ont-sidebar")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  const box = await page.getByTestId("ont-sidebar").boundingBox();
  expect(box!.width).toBeLessThanOrEqual(390);
});
