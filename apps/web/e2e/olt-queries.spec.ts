import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { login } from "./helpers";

const CATALOG_OFF = { enabled: false, limits: { user_per_hour: 10, tenant_per_hour: 60 }, items: [
  { id: "olt.version", title: "Software, patch e uptime", scope: "global", fields: [], validated: true, offered: false, reason: "olt_query_disabled" },
  { id: "olt.board", title: "Placas e estado", scope: "global", fields: [], validated: true, offered: false, reason: "olt_query_disabled" },
  { id: "olt.time", title: "Hora e fuso da OLT", scope: "global", fields: [], validated: true, offered: false, reason: "olt_query_disabled" },
  { id: "olt.sync", title: "Sincronismo de controladoras", scope: "global", fields: [], validated: true, offered: false, reason: "olt_query_disabled" },
  { id: "olt.temperature", title: "Temperatura", scope: "global", fields: [], validated: true, offered: false, reason: "olt_query_disabled" },
] };
const CATALOG_ON = { ...CATALOG_OFF, enabled: true, items: CATALOG_OFF.items.map((i) => ({ ...i, offered: true, reason: null })) };
const VERSION = { product: "MA5608T", version: "MA5600V800R015C00", patch: "SPC100 HP1013", uptime_seconds: 89047277 };
const BOARD = { boards: [{ slot: 0, name: "H805GPFD", status: "Normal" }, { slot: 2, name: "H801MCUD1", status: "Active_normal" }], empty_slots: [3] };
const JOB = "11111111-1111-4111-8111-111111111111";

async function openDrawer(page: import("@playwright/test").Page) {
  await login(page);
  await page.goto("/rede");
  await page.getByTestId("olt-queries-open").first().click();
  await expect(page.getByTestId("olt-queries")).toBeVisible();
}

test("consultas da OLT: com a flag desligada nada é oferecido e o motivo aparece (sem violações de acessibilidade)", async ({ page }) => {
  await page.route("**/bff/olts/*/queries", (r) => r.fulfill({ json: CATALOG_OFF }));
  await openDrawer(page);
  await expect(page.getByTestId("olt-queries-none")).toBeVisible();
  await expect(page.getByTestId("olt-queries")).toContainText("desligada para este provedor");
  await expect(page.getByRole("button", { name: "Pedir consulta" })).toHaveCount(0);
  const a11y = await new AxeBuilder({ page: page as never }).include("dialog").analyze();
  expect(a11y.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? ""))).toEqual([]);
});

test("consultas da OLT: pede olt.version, espera a janela e mostra o resultado tipado", async ({ page }) => {
  let polls = 0;
  await page.route("**/bff/olts/*/queries", (r) => r.fulfill({ json: CATALOG_ON }));
  await page.route("**/bff/olts/*/queries/olt.version", (r) => r.fulfill({ json: { ok: true, outcome: "submitted", job_id: JOB } }));
  await page.route(`**/bff/jobs/${JOB}`, (r) => r.fulfill({ json: ++polls < 2 ? { status: "ACCEPTED", detail: null, data: null } : { status: "SUCCEEDED", detail: "typed result", data: VERSION } }));
  await page.clock.install();
  await openDrawer(page);
  await page.getByRole("radio", { name: /Software, patch e uptime/ }).check();
  await page.getByRole("button", { name: "Pedir consulta" }).click();
  await expect(page.getByTestId("olt-queries-waiting")).toContainText("próxima coleta");
  await page.clock.fastForward(11_000);
  await page.clock.fastForward(11_000);
  const res = page.getByTestId("olt-query-result");
  await expect(res).toContainText("MA5608T");
  await expect(res).toContainText("MA5600V800R015C00");
  await expect(res).toContainText("1030 d");
  const a11y = await new AxeBuilder({ page: page as never }).include("dialog").analyze();
  expect(a11y.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? ""))).toEqual([]);
});

test("consultas da OLT: placas em tabela e falha com a categoria explicada; texto livre do equipamento nunca aparece", async ({ page }) => {
  let mode: "board" | "fail" | "junk" = "board";
  await page.route("**/bff/olts/*/queries", (r) => r.fulfill({ json: CATALOG_ON }));
  await page.route("**/bff/olts/*/queries/*", (r) => r.fulfill({ json: { ok: true, outcome: "submitted", job_id: JOB } }));
  await page.route(`**/bff/jobs/${JOB}`, (r) => r.fulfill({ json:
    mode === "board" ? { status: "SUCCEEDED", detail: "typed result", data: BOARD }
    : mode === "fail" ? { status: "FAILED", detail: "device_rejected", data: null }
    : { status: "SUCCEEDED", detail: "typed result", data: { product: "<img src=x onerror=alert(1)>", version: "x", patch: "y", uptime_seconds: 1 } } }));
  await page.clock.install();
  await openDrawer(page);
  await page.getByRole("radio", { name: /Placas e estado/ }).check();
  await page.getByRole("button", { name: "Pedir consulta" }).click();
  await expect(page.getByTestId("olt-queries-waiting")).toBeVisible();
  await page.clock.fastForward(11_000);
  const table = page.getByTestId("olt-query-result").getByRole("table", { name: "Placas da OLT" });
  await expect(table).toContainText("H801MCUD1");
  await expect(page.getByTestId("olt-queries-done")).toContainText("Slots vazios: 3");
  mode = "fail";
  await page.getByRole("button", { name: "Nova consulta" }).click();
  await page.getByRole("radio", { name: /Placas e estado/ }).check();
  await page.getByRole("button", { name: "Pedir consulta" }).click();
  await expect(page.getByTestId("olt-queries-waiting")).toBeVisible();
  await page.clock.fastForward(11_000);
  await expect(page.getByTestId("olt-queries-failed")).toContainText("O equipamento recusou o comando");
  mode = "junk";
  await page.getByRole("button", { name: "Tentar de novo" }).click();
  await page.getByRole("radio", { name: /Software, patch e uptime/ }).check();
  await page.getByRole("button", { name: "Pedir consulta" }).click();
  await expect(page.getByTestId("olt-queries-waiting")).toBeVisible();
  await page.clock.fastForward(11_000);
  await expect(page.getByTestId("olt-queries-done")).toContainText("formato esperado");
  await expect(page.getByTestId("olt-queries-done")).not.toContainText("onerror");
});

test("consultas da OLT: erros da API viram mensagens estáveis", async ({ page }) => {
  await page.route("**/bff/olts/*/queries", (r) => r.fulfill({ json: CATALOG_ON }));
  await page.route("**/bff/olts/*/queries/olt.version", (r) => r.fulfill({ status: 429, json: { error: "olt_query_quota" } }));
  await openDrawer(page);
  await page.getByRole("button", { name: "Pedir consulta" }).click();
  await expect(page.getByTestId("olt-queries-error")).toContainText("Limite de consultas por hora");
});

test("consultas da OLT: fechar a gaveta para o polling e reabrir retoma o MESMO pedido; trocar a seleção não muda o que foi pedido", async ({ page }) => {
  let polls = 0;
  const posted: string[] = [];
  await page.route("**/bff/olts/*/queries", (r) => r.fulfill({ json: CATALOG_ON }));
  await page.route("**/bff/olts/*/queries/*", async (r) => { posted.push(new URL(r.request().url()).pathname.split("/").pop() ?? ""); await r.fulfill({ json: { ok: true, outcome: "submitted", job_id: JOB } }); });
  await page.route(`**/bff/jobs/${JOB}`, (r) => { polls++; return r.fulfill({ json: polls < 3 ? { status: "ACCEPTED", detail: null, data: null } : { status: "SUCCEEDED", detail: "typed result", data: VERSION } }); });
  await page.clock.install();
  await openDrawer(page);
  await page.getByRole("radio", { name: /Software, patch e uptime/ }).check();
  await page.getByRole("button", { name: "Pedir consulta" }).click();
  await expect(page.getByTestId("olt-queries-waiting")).toBeVisible();
  expect(posted).toEqual(["olt.version"]);
  await page.clock.fastForward(11_000);
  await expect.poll(() => polls).toBe(1);
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("entity-drawer")).toBeHidden();
  await page.clock.fastForward(60_000);
  expect(polls).toBe(1);                                       // closed: nobody is asking
  await page.getByTestId("olt-queries-open").first().click();
  await expect(page.getByTestId("olt-queries-waiting")).toBeVisible();   // the same request is still there
  await page.clock.fastForward(11_000);
  await page.clock.fastForward(11_000);
  await expect(page.getByTestId("olt-query-result")).toContainText("MA5608T");
  expect(posted).toEqual(["olt.version"]);                      // nothing was asked twice
});


test("consultas da OLT: hora, sincronismo e temperatura mostram só o formato fechado", async ({ page }) => {
  let data: unknown = { time: "2026-10-30T20:42:45-04:00" };
  await page.route("**/bff/olts/*/queries", (r) => r.fulfill({ json: CATALOG_ON }));
  await page.route("**/bff/olts/*/queries/*", (r) => r.fulfill({ json: { ok: true, outcome: "submitted", job_id: JOB } }));
  await page.route(`**/bff/jobs/${JOB}`, (r) => r.fulfill({ json: { status: "SUCCEEDED", detail: "typed result", data } }));
  await page.clock.install();
  await openDrawer(page);
  const ask = async (name: RegExp) => {
    await page.getByRole("radio", { name }).check();
    await page.getByRole("button", { name: "Pedir consulta" }).click();
    await expect(page.getByTestId("olt-queries-waiting")).toBeVisible();
    await page.clock.fastForward(11_000);
  };
  await ask(/Hora e fuso da OLT/);
  await expect(page.getByTestId("olt-query-result")).toContainText("30/10/2026 20:42:45 (fuso -04:00)");
  data = { standby: "absent_or_fault" };
  await page.getByRole("button", { name: "Nova consulta" }).click();
  await ask(/Sincronismo de controladoras/);
  await expect(page.getByTestId("olt-query-result")).toContainText("Sem placa de controle reserva");
  data = { boards: [{ slot: 0, name: "H805GPFD", celsius: 45 }, { slot: 2, name: "H801MCUD1", celsius: 43 }] };
  await page.getByRole("button", { name: "Nova consulta" }).click();
  await ask(/Temperatura/);
  await expect(page.getByTestId("olt-query-result").getByRole("table", { name: "Temperatura das placas" })).toContainText("45 °C");
  data = { boards: [{ slot: 0, name: "<img src=x onerror=alert(1)>", celsius: 45 }] };
  await page.getByRole("button", { name: "Nova consulta" }).click();
  await ask(/Temperatura/);
  await expect(page.getByTestId("olt-queries-done")).toContainText("não tinha o formato esperado");
  await expect(page.locator("img[src='x']")).toHaveCount(0);
  const a11y = await new AxeBuilder({ page: page as never }).include("dialog").analyze();
  expect(a11y.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? ""))).toEqual([]);
});
