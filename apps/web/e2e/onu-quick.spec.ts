import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { login } from "./helpers";

// Painel da ONU (UX 2.2 / ADR-0037): dados do seed — OLT-DEMO-01 (DEMOA0001 online, DEMOA0003 online, DEMOC0000 LOS), DEMOQ0001 (OLT-QUICK-01, coleta recente), DEMOQ0002 (OLT-QUICK-02, coleta de 3 h atrás).
const row = (page: import("@playwright/test").Page, serial: string) => page.getByTestId("onu-open").filter({ hasText: serial });

test("resumo rápido: painel ao lado da lista, PON e ACS separados, trocar a ONU substitui o conteúdo, Esc fecha e devolve o foco", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await login(page);
  await page.goto("/rede");
  await expect(page.getByTestId("onu-quick-empty")).toContainText("Selecione uma ONU");   // o painel já existe, vazio, antes de escolher
  await row(page, "DEMOA0001").click();
  const panel = page.getByTestId("onu-quick");
  await expect(panel).toHaveAttribute("data-mode", "panel");
  await expect(panel.getByRole("heading", { name: "DEMOA0001" })).toBeVisible();
  await expect(panel).toContainText("PON registrada");
  await expect(panel).toContainText("Origem: OLT");
  await expect(panel).toContainText("Sem roteador vinculado");           // ACS ausente não vira "offline" nem "ok"
  await expect(panel).toContainText("RX -21,5 dBm");
  await expect(panel).toContainText("sem limiar homologado");
  await expect(panel.getByTestId("faceplate-mini")).toHaveAttribute("aria-label", /Energia e sincronismo presentes/);
  await expect(panel).toContainText("Painel conceitual");
  // não modal: a lista segue clicável com o painel aberto e o painel troca de conteúdo (nunca mostra o da anterior)
  await row(page, "DEMOC0000").click();
  await expect(panel.getByRole("heading", { name: "DEMOC0000" })).toBeVisible();
  await expect(panel).toContainText("PON offline · sem sinal (LOS)");
  await expect(panel).not.toContainText("PON registrada");
  await expect(panel.getByTestId("faceplate-mini")).toHaveAttribute("aria-label", /indício de fibra\/LOS/);
  await row(page, "DEMOC0000").click();                                   // clicar de novo na mesma ONU não fecha
  await expect(panel).toBeVisible();
  const a11y = await new AxeBuilder({ page: page as never }).include("[data-testid=onu-quick]").analyze();
  expect(a11y.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? ""))).toEqual([]);
  await page.keyboard.press("Escape");
  await expect(panel).toBeHidden();
  await expect(page.getByTestId("onu-quick-empty")).toBeVisible();
  await expect(row(page, "DEMOC0000")).toBeFocused();
  // dado defasado nunca fica verde nem vira "fora": painel esvaziado e texto honesto
  await page.goto("/rede?serial=DEMOQ0002");
  await row(page, "DEMOQ0002").click();
  await expect(panel).toContainText("PON: dados defasados");
  await expect(panel.getByTestId("faceplate-mini")).toHaveAttribute("aria-label", /defasado/);
  // o botão leva à ONU 360° e a lista de volta continua igual
  await page.goto("/rede");
  await row(page, "DEMOA0001").click();
  await page.getByTestId("onu-360-link").click();
  await expect(page).toHaveURL(/\/rede\/onu\/[0-9a-f-]{36}$/);
  await expect(page.getByRole("heading", { name: "ONU DEMOA0001" })).toBeVisible();
});

test("resumo rápido: resposta atrasada de outra ONU nunca aparece, e uma falha do resumo não derruba a lista", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await login(page);
  await page.goto("/rede");
  let slow = true;
  await page.route("**/bff/onus/*/quick", async (r) => {
    if (slow) { slow = false; await new Promise((res) => setTimeout(res, 1500)); }   // a primeira ONU pedida responde tarde
    await r.continue();
  });
  await row(page, "DEMOA0001").click();
  await row(page, "DEMOC0000").click();
  const panel = page.getByTestId("onu-quick");
  await expect(panel).toContainText("PON offline · sem sinal (LOS)");
  await page.waitForTimeout(2000);                                         // a resposta atrasada da ONU anterior chegou (ou foi cancelada): nada muda
  await expect(panel.getByRole("heading", { name: "DEMOC0000" })).toBeVisible();
  await expect(panel).not.toContainText("PON registrada");
  await page.unroute("**/bff/onus/*/quick");
  await page.route("**/bff/onus/*/quick", (r) => r.fulfill({ status: 502, json: { error: "failed" } }));
  await row(page, "DEMOA0001").click();
  await expect(page.getByTestId("onu-quick-error")).toContainText("Não foi possível carregar o resumo");
  await expect(panel).toContainText("OLT-DEMO-01");                        // identidade/OLT da linha seguem visíveis
  await expect(page.getByTestId("onu-quick-error").getByRole("button", { name: "Tentar novamente" })).toBeVisible();
  await expect(row(page, "DEMOA0003")).toBeVisible();                      // a lista não caiu
});

test("resumo rápido: o BFF compõe só leitura e devolve o formato fechado (estados por fonte)", async ({ page }) => {
  await login(page);
  const ids: Record<string, string> = {};
  for (const s of ["DEMOQ0001", "DEMOQ0002", "DEMOC0000"]) {
    await page.goto(`/rede?serial=${s}`);
    await row(page, s).click();
    await page.getByTestId("onu-360-link").click();
    await page.waitForURL(/\/rede\/onu\/[0-9a-f-]{36}$/);
    ids[s] = page.url().split("/").pop()!;
  }
  const get = async (s: string) => {
    const r = await page.request.get(`/bff/onus/${ids[s]}/quick`);
    expect(r.status(), `${s}: ${await r.text()}`).toBe(200);
    return (await r.json()).model;
  };
  const fresh = await get("DEMOQ0001");
  expect(fresh.pon).toMatchObject({ label: "PON registrada", tone: "ok", fresh: true, source: "olt" });
  expect(fresh.acs).toMatchObject({ label: "Sem roteador vinculado", tone: "neutral", source: null });
  expect(fresh.optical).toMatchObject({ rx_dbm: -18.75, severity: "unknown", source: "olt" });
  expect(fresh.association.state).toMatch(/unassociated|restricted/);
  expect(fresh.association.customer).toBeNull();
  const stale = await get("DEMOQ0002");
  expect(stale.pon).toMatchObject({ label: "PON: dados defasados", tone: "neutral", fresh: false });
  const los = await get("DEMOC0000");
  expect(los.pon).toMatchObject({ tone: "bad" });
  expect(JSON.stringify([fresh, stale, los])).not.toMatch(/password|senha|psk/i);
  expect((await page.request.get("/bff/onus/nao-e-uuid/quick")).status()).toBe(400);
  // um resumo de OUTRA ONU (resposta adulterada ou trocada) nunca é usado pelo painel
  await page.goto("/rede");
  await row(page, "DEMOA0001").click();
  await page.route("**/bff/onus/*/quick", async (r) => {
    const real = await (await r.fetch()).json();
    await r.fulfill({ json: { model: { ...real.model, onu: { ...real.model.onu, id: ids["DEMOC0000"] } } } });
  });
  await row(page, "DEMOA0003").click();
  await expect(page.getByTestId("onu-quick-error")).toContainText("Não foi possível carregar o resumo");
  await expect(page.getByTestId("onu-quick")).not.toContainText("Origem: OLT");
  expect((await page.request.get("/bff/onus/00000000-0000-0000-0000-000000000000/quick")).status()).toBe(404);
});

test("resumo rápido: no celular vira gaveta modal sem rolagem lateral", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page);
  await page.goto("/rede?serial=DEMOQ0001");
  await row(page, "DEMOQ0001").click();
  const sheet = page.getByTestId("onu-quick");
  await expect(sheet).toHaveAttribute("data-mode", "sheet");
  const dlg = sheet.locator("xpath=ancestor::dialog");
  await expect(dlg).toBeVisible();
  await expect(sheet).toContainText("PON registrada");
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
  await page.keyboard.press("Escape");
  await expect(dlg).toBeHidden();
});
