import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext } from "@playwright/test";
import { API_URL, EMAIL, login, PASSWORD } from "./helpers";

// Painel frontal vetorial da MA5608T (pacote FiberCore-MA5608T v1.0) na stack real com o seed SINTÉTICO (OLT-DEMO-PAINEL, inventário de placas 'mock').
const oltId = async (request: APIRequestContext, name: string) => {
  const tok = (await (await request.post(`${API_URL}/v1/auth/token`, { data: { email: EMAIL, password: PASSWORD } })).json()).access_token as string;
  const list = (await (await request.get(`${API_URL}/v1/olts?limit=200`, { headers: { Authorization: `Bearer ${tok}` } })).json()) as { id: string; name: string }[];
  return list.find((o) => o.name === name)!.id;
};

test("painel da MA5608T: dois cartões, 16 PON por slot, LED por PON e popover com ONUs UP/DOWN", async ({ page, request }) => {
  await login(page);
  await page.goto(`/rede?olt=${await oltId(request, "OLT-DEMO-PAINEL")}`);
  const painel = page.getByTestId("olt-panel");
  await expect(painel).toBeVisible();
  await expect(page.getByTestId("olt-panel-note")).toContainText("DEMONSTRAÇÃO");
  await expect(page.getByTestId("olt-slot")).toHaveCount(2);
  await expect(page.getByTestId("olt-pon")).toHaveCount(32);
  const keys = await page.getByTestId("olt-pon").evaluateAll((els) => els.map((e) => e.getAttribute("data-port-key")));
  expect(keys).toEqual([...Array.from({ length: 16 }, (_, i) => `0/0/${i}`), ...Array.from({ length: 16 }, (_, i) => `0/1/${i}`)]);
  const led = (k: string) => page.locator(`[data-testid="olt-pon"][data-port-key="${k}"]`);
  await expect(led("0/0/0")).toHaveAttribute("data-led", "up");
  await expect(led("0/0/1")).toHaveAttribute("data-led", "warning");   // PON UP com ONUs fora: atenção, não DOWN
  await expect(led("0/0/2")).toHaveAttribute("data-led", "warning");   // todas as ONUs lidas fora, porta não lida
  await expect(led("0/0/3")).toHaveAttribute("data-led", "unknown");   // sem ONUs lidas: nada é afirmado
  await expect(led("0/1/0")).toHaveAttribute("data-led", "up");

  // clique abre o popover pequeno, sem sair da tela
  await led("0/0/1").click();
  const pop = page.getByTestId("olt-popover");
  await expect(pop).toBeVisible();
  await expect(pop).toContainText("PON 0/0/1");
  await expect(page.getByTestId("olt-popover-up")).toHaveText("9");
  await expect(page.getByTestId("olt-popover-down")).toHaveText("3");
  await expect(page.getByTestId("olt-popover-operational")).toContainText("UP (por ONU online)");
  await expect(page.getByTestId("olt-popover-condition")).toHaveText("ATENÇÃO");
  await expect(page).toHaveURL(/\/rede\?olt=/);
  // Escape fecha e devolve o foco à PON
  await page.keyboard.press("Escape");
  await expect(pop).toBeHidden();
  await expect(led("0/0/1")).toBeFocused();
  // teclado: Enter abre; porta cujo estado não foi lido não vira DOWN
  await led("0/0/2").focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("olt-popover-operational")).toHaveText("não lido");
  await expect(page.getByTestId("olt-popover-up")).toHaveText("0");
  await expect(page.getByTestId("olt-popover-down")).toHaveText("4");
  await expect(page.getByTestId("olt-popover-note")).toContainText("pode ser a PON");
  // clique fora fecha
  await page.getByTestId("olt-panel-note").click();
  await expect(pop).toBeHidden();
  // PON sem leitura: popover diz isso e não mostra zero fingindo leitura de porta
  await led("0/0/3").click();
  await expect(page.getByTestId("olt-popover-condition")).toHaveText("SEM LEITURA");
  await expect(page.getByTestId("olt-popover-operational")).toHaveText("não lido");
  // o painel é recolhível e o resto da tela segue (a matriz de PONs continua)
  await painel.locator("summary").click();
  await expect(page.getByTestId("olt-svg")).toBeHidden();
  await expect(page.getByTestId("pon-matrix")).toBeVisible();
  await painel.locator("summary").click();
  await expect(page.getByTestId("olt-svg")).toBeVisible();
  const a11y = await new AxeBuilder({ page: page as never }).analyze();
  expect(a11y.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? ""))).toEqual([]);
});

test("painel da MA5608T no celular: sem rolagem horizontal e o popover cabe na tela", async ({ page, request }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page);
  await page.goto(`/rede?olt=${await oltId(request, "OLT-DEMO-PAINEL")}`);
  await page.locator('[data-testid="olt-pon"][data-port-key="0/0/1"]').click();
  const pop = page.getByTestId("olt-popover");
  await expect(pop).toBeVisible();
  const box = (await pop.boundingBox())!;
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(390 + 1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
});

test("outras OLTs não ganham o painel da MA5608T", async ({ page, request }) => {
  await login(page);
  await page.goto(`/rede?olt=${await oltId(request, "OLT-DEMO-01")}`);
  await expect(page.getByTestId("onu-inventory-ready")).toBeVisible();
  await expect(page.getByTestId("olt-panel")).toHaveCount(0);
  await expect(page.getByTestId("pon-matrix")).toBeVisible();
});
