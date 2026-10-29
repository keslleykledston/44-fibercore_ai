import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { login } from "./helpers";

// Este arquivo roda DEPOIS de app/help-screenshots (ordem alfabética, 1 worker): reconhecer o incidente demo muda o estado que aqueles usam.

test("reconhecer incidente pelo painel: botão some, fila e indicador acompanham, sem ação na rede", async ({ page }) => {
  await login(page);
  await page.goto("/noc");
  const kpi = page.getByTestId("noc-kpis");
  await expect(kpi).toContainText("Não reconhecidos");
  const before = Number((await kpi.getByTestId("kpi-Não reconhecidos").innerText()).match(/\d+/)![0]);
  expect(before).toBeGreaterThan(0);
  const first = page.getByTestId("incident-item").first();
  await expect(first).toContainText("Não reconhecido");
  await first.getByTestId("incident-open").click();
  const box = page.getByTestId("incident-ack");
  await expect(box).toContainText("Não altera nada na rede");
  const res = await new AxeBuilder({ page: page as never }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  expect(res.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => v.id)).toEqual([]);
  await page.getByTestId("ack-button").click();
  await expect(page.getByTestId("ack-done")).toBeVisible();
  await expect(page.getByTestId("ack-button")).toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(first).toContainText("Reconhecido");
  await expect(first).not.toContainText("Não reconhecido");
  await expect.poll(async () => Number((await kpi.getByTestId("kpi-Não reconhecidos").innerText()).match(/\d+/)![0])).toBe(before - 1); // indicador do servidor
  await page.reload();                                                                              // persistiu no servidor
  await expect(page.getByTestId("incident-item").first()).toContainText("Reconhecido");
});

test("busca global acha cliente por nome (a partir de 3 letras) e abre a Visão 360", async ({ page }) => {
  await login(page);
  await page.getByLabel("Abrir busca global").click();
  const input = page.getByLabel("Buscar telas, ONU por serial ou cliente por nome");
  await input.fill("Cl");
  await expect(page.getByRole("option", { name: /Cliente Demo/ })).toHaveCount(0);   // menos de 3 letras: nenhuma consulta de cliente
  await input.fill("Cliente Demo Um");
  const hit = page.getByRole("option", { name: /^Cliente\s*Cliente Demo Um/ });
  await expect(hit).toBeVisible();
  await expect(page.getByRole("listbox")).not.toContainText("1234");                  // só nome: nada de documento
  await hit.click();
  await expect(page).toHaveURL(/\/assinantes\/[0-9a-f-]{36}$/);
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Cliente Demo Um");
});
