import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext } from "@playwright/test";
import { API_URL, EMAIL, login, PASSWORD } from "./helpers";

// Gestão de ONUs (ADR-0037, padrão Lovable): matriz de PONs, árvore, lista com filtros e painel lado a lado, abas Resumo / Aparelho / Histórico. Seed: OLT-DEMO-01 (PON 0/1/0: A0000-A0011 online + B offline; PON 0/1/1: C0000-C0009 LOS).
const row = (page: import("@playwright/test").Page, serial: string) => page.getByTestId("onu-open").filter({ hasText: serial });

/** Confirma (idempotente) o vínculo ONU↔CPE de DEMOA0002: só com roteador vinculado a aba "Aparelho" existe. */
async function confirmDemoA2(request: APIRequestContext) {
  const tok = (await (await request.post(`${API_URL}/v1/auth/token`, { data: { email: EMAIL, password: PASSWORD } })).json()).access_token as string;
  const h = { Authorization: `Bearer ${tok}` };
  expect((await request.post(`${API_URL}/v1/onu-cpe-links/suggest`, { headers: h })).status()).toBe(201);
  const links = (await (await request.get(`${API_URL}/v1/onu-cpe-links?status=suggested&limit=200`, { headers: h })).json()) as { id: string; onu: { serial: string } }[];
  const mine = links.find((l) => l.onu.serial === "DEMOA0002");
  if (mine) expect((await request.post(`${API_URL}/v1/onu-cpe-links/${mine.id}/confirm`, { headers: h })).status()).toBe(200);
}

test("gestão: matriz de PONs com resumo em texto, árvore e trilha; a célula leva à PON", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await login(page);
  await page.goto("/rede");
  const matrix = page.getByTestId("pon-matrix");
  await expect(matrix).toContainText("Painel frontal");
  const los = matrix.locator('[data-testid="pon-cell"][data-state="los"]');
  await expect(los).toHaveCount(1);
  await expect(los).toContainText("0/1/1");
  await expect(los).toContainText("Perda de sinal óptico (LOS)");     // o estado também vem em texto (cor não é o único indicador)
  await expect(los).toContainText("10 fora");
  await expect(matrix.locator('[data-testid="pon-cell"][data-state="fora"]')).toContainText("0/1/0");   // as 2 B offline: fora do ar, sem causa
  const tree = page.getByTestId("pon-tree");
  await expect(tree).toContainText("PON 0/1/1");
  await los.click();
  await expect(page).toHaveURL(/pon=0%2F1%2F1/);
  await expect(page.getByRole("heading", { name: "PON 0/1/1" })).toBeVisible();
  await expect(page.getByTestId("rede-breadcrumb")).toContainText("OLT-DEMO-01");
  await expect(row(page, "DEMOC0000")).toBeVisible();
  await expect(row(page, "DEMOA0001")).toHaveCount(0);                // só as ONUs desta PON
  await expect(page.getByTestId("onu-count")).toHaveText("10 ONUs");
  await expect(page.getByTestId("pon-tree").getByRole("link", { name: /PON 0\/1\/1/ })).toHaveAttribute("aria-current", "page");
  await page.getByTestId("rede-breadcrumb").getByRole("link", { name: "OLT-DEMO-01" }).click();
  await expect(row(page, "DEMOA0001")).toBeVisible();
  // outra OLT pela árvore
  await page.getByTestId("pon-tree").getByRole("link", { name: /OLT-QUICK-01/ }).click();
  await expect(row(page, "DEMOQ0001")).toBeVisible();
  await expect(row(page, "DEMOA0001")).toHaveCount(0);
});

test("gestão: as três colunas ficam lado a lado e nenhuma coluna da lista some atrás do painel", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await login(page);
  await page.goto("/rede");
  const th = page.locator("th", { hasText: "Dado" });
  await expect(th).toBeVisible();
  await row(page, "DEMOA0001").click();
  const panel = page.getByTestId("onu-quick");
  await expect(panel).toBeVisible();
  const tree = await page.getByTestId("pon-tree").boundingBox();
  const table = await page.locator("table").first().boundingBox();
  const pane = await panel.boundingBox();
  const last = await th.boundingBox();
  expect(tree!.x + tree!.width).toBeLessThanOrEqual(table!.x + 1);            // árvore | lista | painel, em ordem e sem sobrepor
  expect(table!.x + table!.width).toBeLessThanOrEqual(pane!.x + 1);
  expect(last!.x + last!.width).toBeLessThanOrEqual(pane!.x + 1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
});

test("gestão: filtros por estado e por serial, contagem anunciada e painel mantido", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await login(page);
  await page.goto("/rede");
  const total = await page.getByTestId("onu-open").count();
  await expect(page.getByTestId("onu-count")).toHaveText(`${total} ONUs`);
  await row(page, "DEMOA0001").click();
  await page.getByRole("radio", { name: /Fora do ar/ }).click();
  await expect(row(page, "DEMOC0000")).toBeVisible();                        // LOS conta como fora do ar
  await expect(row(page, "DEMOA0001")).toHaveCount(0);
  await expect(page.getByTestId("onu-count")).toContainText(`de ${total} ONUs`);
  await expect(page.getByTestId("onu-quick")).toContainText("DEMOA0001");    // filtrar não fecha o painel da ONU escolhida
  await expect(page.getByRole("radio", { name: /Fora do ar/ })).toHaveAttribute("aria-checked", "true");
  await page.getByRole("radio", { name: /Todas/ }).click();
  await expect(page.getByTestId("onu-count")).toHaveText(`${total} ONUs`);
  await page.getByLabel("Filtrar por serial").fill("democ000");
  await expect(page.getByTestId("onu-count")).toHaveText(`10 de ${total} ONUs`);
  await page.getByLabel("Filtrar por serial").fill("naoexiste");
  await expect(page.getByText("Nenhuma ONU com este filtro.")).toBeVisible();
});

test("gestão: abas Resumo, Aparelho (só com roteador vinculado) e Histórico; trocar a ONU volta ao Resumo", async ({ page, request }) => {
  await confirmDemoA2(request);
  await page.setViewportSize({ width: 1440, height: 900 });
  await login(page);
  await page.goto("/rede");
  await row(page, "DEMOA0001").click();
  const panel = page.getByTestId("onu-quick");
  await expect(panel.getByRole("tab", { name: "Resumo" })).toHaveAttribute("aria-selected", "true");
  await expect(panel.getByRole("tab", { name: "Aparelho" })).toHaveCount(0);   // sem roteador vinculado: a aba não existe (nada inventado)
  await panel.getByRole("tab", { name: "Histórico" }).click();
  await expect(page.getByTestId("onu-history")).toContainText("Quedas (30 dias)");
  await expect(page.getByTestId("onu-history")).toContainText("Primeira observação");
  // ONU com roteador confirmado: aba Aparelho com a configuração SOMENTE LEITURA (perfil sintético rotulado)
  await row(page, "DEMOA0002").click();
  await expect(panel.getByRole("tab", { name: "Resumo" })).toHaveAttribute("aria-selected", "true");
  await panel.getByRole("tab", { name: "Aparelho" }).click();
  const dev = page.getByTestId("onu-device-tab");
  await expect(dev).toContainText("Leitura recente");
  await expect(dev.getByTestId("ont-synthetic")).toContainText("sintéticos");
  await expect(dev.getByTestId("ont-optical")).toContainText("Potência recebida");
  await dev.getByRole("tab", { name: "Wi-Fi" }).click();
  await expect(dev.getByLabel("Nome da rede")).toHaveValue("Rede_Demo_2G");
  for (const i of await dev.locator("input").all()) await expect(i).toHaveAttribute("readonly", "");
  await expect(dev.getByRole("button", { name: /salvar|aplicar|enviar|pré-visualizar/i })).toHaveCount(0);
  const a11y = await new AxeBuilder({ page: page as never }).include("[data-testid=onu-quick]").analyze();
  expect(a11y.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? ""))).toEqual([]);
  await row(page, "DEMOC0000").click();                                       // outra ONU: volta para o Resumo e nada do aparelho anterior sobra
  await expect(panel.getByRole("tab", { name: "Resumo" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("onu-device-tab")).toHaveCount(0);
});

test("gestão: falha do histórico mostra erro com nova tentativa e não derruba o painel", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await login(page);
  await page.goto("/rede");
  await page.route("**/bff/onus/*/history", (r) => r.fulfill({ status: 502, json: { error: "failed" } }));
  await row(page, "DEMOA0001").click();
  await page.getByTestId("onu-quick").getByRole("tab", { name: "Histórico" }).click();
  await expect(page.getByTestId("onu-history-error")).toContainText("não está disponível agora");
  await expect(page.getByTestId("onu-history-error").getByRole("button", { name: "Tentar novamente" })).toBeVisible();
  await page.getByTestId("onu-quick").getByRole("tab", { name: "Resumo" }).click();
  await expect(page.getByTestId("onu-quick")).toContainText("PON registrada");
});

test("gestão: no celular as abas ficam na gaveta e não há rolagem lateral", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page);
  await page.goto("/rede");
  await row(page, "DEMOA0001").click();
  const sheet = page.getByTestId("onu-quick");
  await expect(sheet.getByRole("tab", { name: "Histórico" })).toBeVisible();
  await sheet.getByRole("tab", { name: "Histórico" }).click();
  await expect(page.getByTestId("onu-history")).toBeVisible();
  await page.keyboard.press("Escape");
  await page.getByTestId("pon-matrix").scrollIntoViewIfNeeded();
  await expect(page.getByTestId("pon-cell").first()).toBeVisible();          // matriz de PONs também no celular
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
});

test("ONU 360°: trilha até a PON e painel frontal com óptica no alto; LOS aparece em texto e dado velho esvazia o painel", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await login(page);
  await page.goto("/rede?serial=DEMOC0000");
  await row(page, "DEMOC0000").click();
  await page.getByTestId("onu-360-link").click();
  await expect(page.getByRole("heading", { name: "ONU DEMOC0000" })).toBeVisible();
  const crumb = page.getByTestId("onu360-breadcrumb");
  await expect(crumb).toContainText("OLT-DEMO-01");
  await expect(crumb).toContainText("PON 0/1/1");
  await crumb.getByRole("link", { name: "PON 0/1/1" }).click();
  await expect(page).toHaveURL(/olt=.*&pon=0%2F1%2F1/);
  await page.goBack();
  const card = page.getByTestId("onu360-faceplate");
  await expect(card).toContainText("Painel frontal");
  await expect(card).toContainText("indício de fibra/LOS");
  await expect(card.getByTestId("faceplate-legend")).toContainText("LOS · Piscando rápido");
  await expect(card).toContainText("Sem limiar homologado");                 // óptica sem cor de severidade inventada
  await expect(card).toContainText("derivado do que a OLT reportou");
  const a11y = await new AxeBuilder({ page: page as never }).include("[data-testid=onu360-faceplate]").analyze();
  expect(a11y.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? ""))).toEqual([]);
  await page.goto("/rede?serial=DEMOQ0002");                                 // coleta de 3 h atrás
  await row(page, "DEMOQ0002").click();
  await page.getByTestId("onu-360-link").click();
  await expect(page.getByTestId("onu360-faceplate").getByTestId("faceplate").first()).toHaveAttribute("data-last-known", "true");
  await expect(page.getByTestId("onu360-faceplate")).toContainText("Isso não significa que o equipamento esteja desligado");
});
