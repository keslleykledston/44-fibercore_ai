import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { login } from "./helpers";

// Catálogo de equipamentos (ADR-0041, PR1): arte esquemática por modelo, sempre rotulada; nenhuma porta, LED ou estado vem da imagem.
test("catálogo: 69 equipamentos de 8 fabricantes, aviso de fidelidade e rótulo em todo cartão", async ({ page }) => {
  await login(page);
  await page.goto("/rede");
  await page.getByTestId("rede-catalogo-link").click();
  await expect(page).toHaveURL(/\/rede\/catalogo$/);
  await expect(page.getByTestId("catalogo-aviso")).toContainText("Não é foto nem desenho exato");
  await expect(page.getByTestId("catalogo-contagem")).toContainText("69 de 69 equipamentos · 8 fabricantes");
  const items = page.getByTestId("catalogo-item");
  await expect(items).toHaveCount(69);
  await expect(page.getByTestId("catalogo-fidelidade")).toHaveCount(69);
  await expect(page.getByTestId("catalogo-fidelidade").first()).toHaveText("Ilustração esquemática");
  await expect(page.getByTestId("catalogo-grade")).not.toContainText(/verificad[oa]/i);   // nada se declara verificado
  // as miniaturas são locais (nenhuma imagem de outro endereço) e carregam de verdade
  const srcs = await page.locator('[data-testid="catalogo-item"] img').evaluateAll((els) => els.map((e) => (e as HTMLImageElement).getAttribute("src")));
  expect(srcs.every((s) => !!s && s.startsWith("/devices/svg/"))).toBe(true);
  await page.evaluate(async () => { for (const i of Array.from(document.images)) i.loading = "eager"; await Promise.all(Array.from(document.images).map((i) => (i.complete ? 0 : new Promise((r) => { i.onload = i.onerror = r; })))); });
  const broken = await page.locator('[data-testid="catalogo-item"] img').evaluateAll((els) => els.filter((e) => (e as HTMLImageElement).naturalWidth === 0).length);
  expect(broken).toBe(0);
  const res = await new AxeBuilder({ page: page as never }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  expect(res.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => v.id)).toEqual([]);
});

test("catálogo: busca por fabricante e modelo e filtros de tipo e fabricante", async ({ page }) => {
  await login(page);
  await page.goto("/rede/catalogo?q=huawei%20ma5608");
  await expect(page.locator('[data-testid="catalogo-item"][data-asset="olt-huawei-ma5608t"]')).toHaveCount(1);
  await page.goto("/rede/catalogo?tipo=olt");
  await expect(page.getByTestId("catalogo-item")).toHaveCount(28);
  await page.goto("/rede/catalogo?tipo=onu_ont&fab=zte");
  const n = await page.getByTestId("catalogo-item").count();
  expect(n).toBeGreaterThan(0);
  await page.goto("/rede/catalogo?fab=inexistente&q=zzzzzz");
  await expect(page.getByText("Nenhum equipamento encontrado")).toBeVisible();
  await expect(page.getByTestId("catalogo-grade")).toHaveCount(0);
});

test("Rede: a OLT mostra a miniatura pelo modelo que ela informou; modelo fora do catálogo usa o desenho neutro e diz 'Sem arte catalogada'", async ({ page }) => {
  await login(page);
  await page.goto("/rede");
  const thumb = page.getByTestId("olt-header-thumb").getByTestId("device-thumb");
  await expect(thumb).toBeVisible();
  const fid = await thumb.getAttribute("data-fidelity");
  expect(["SCHEMATIC", "UNKNOWN"]).toContain(fid);
  if (fid === "UNKNOWN") {
    await expect(thumb).toContainText("Sem arte catalogada");
    await expect(thumb.locator("img")).toHaveAttribute("src", "/devices/svg/generic-olt.svg");
    await expect(thumb.locator("img")).toHaveAttribute("alt", /sem arte catalogada/i);
  } else {
    await expect(thumb).toContainText("Ilustração esquemática");
  }
  // a imagem não traz porta, LED nem estado: o painel e a matriz de PONs seguem sendo outros elementos, do inventário
  await expect(thumb.getByTestId("olt-pon")).toHaveCount(0);
});

test("catálogo: parâmetros repetidos ou estranhos na URL não derrubam a página", async ({ page }) => {
  await login(page);
  for (const qs of ["?q=huawei&q=zte", "?tipo=olt&tipo=onu_ont", "?fab=zte&fab=huawei&q=x&q=y", "?q=%00%FF", "?q=" + "a".repeat(500), "?tipo[]=olt&fab[x]=1"]) {
    const r = await page.goto(`/rede/catalogo${qs}`);
    expect(r?.status(), qs).toBe(200);
    await expect(page.getByTestId("catalogo-contagem"), qs).toContainText("equipamentos");
  }
  await page.goto("/rede/catalogo?q=huawei&q=zte");
  await expect(page.locator('[data-testid="catalogo-item"][data-asset="olt-huawei-ma5608t"]')).toHaveCount(1);   // vale o primeiro valor
});
