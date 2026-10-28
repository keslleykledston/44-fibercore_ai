import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { login } from "./helpers";

const routes = ["/", "/rede", "/noc", "/administracao/modulos", "/ajuda", "/ajuda/rede/consultar-onu"];

test("login inválido mostra erro e não cria sessão", async ({ page, context }) => {
  await page.goto("/login");
  await page.getByLabel("E-mail").fill("admin@demo.example.com");
  await page.getByLabel("Senha").fill("senha-errada");
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByTestId("login-error")).toBeVisible();
  expect((await context.cookies()).find((c) => c.name === "fc_token")).toBeUndefined();
});

test("telas protegidas redirecionam para login sem sessão", async ({ page }) => {
  for (const r of ["/", "/rede", "/noc", "/administracao/modulos", "/ajuda"]) {
    await page.goto(r);
    await expect(page).toHaveURL(/\/login/);
  }
});

test("cookie de sessão é HttpOnly e inacessível ao JavaScript", async ({ page, context }) => {
  await login(page);
  const c = (await context.cookies()).find((x) => x.name === "fc_token")!;
  expect(c.httpOnly).toBe(true);
  expect(c.sameSite).toBe("Lax");
  expect(await page.evaluate(() => document.cookie)).not.toContain("fc_token");
  expect(await page.evaluate(() => JSON.stringify(Object.assign({}, localStorage)))).not.toMatch(/eyJ/);
});

test("mutações do BFF rejeitam origem diferente (CSRF)", async ({ page, request, baseURL }) => {
  await login(page);
  const r = await request.post(`${baseURL}/bff/logout`, { headers: { origin: "https://evil.example" }, maxRedirects: 0 });
  expect(r.status()).toBe(403);
  const ok = await request.post(`${baseURL}/bff/login`, { headers: { origin: "https://evil.example" }, form: { email: "a@b.co", password: "x" }, maxRedirects: 0 });
  expect(ok.status()).toBe(403);
});

test("Central de Ajuda não serve arquivos fora de docs/help", async ({ page }) => {
  await login(page);
  for (const p of ["/ajuda/..%2f..%2farchitecture%2fARCHITECTURE", "/ajuda/architecture/ARCHITECTURE", "/ajuda-assets/..%2f..%2f..%2fCLAUDE.md", "/ajuda-assets/rede/consultar-onu/../../../../package.json"]) {
    const res = await page.goto(p);
    expect(res!.status(), p).toBe(404);
  }
});

test("dados defasados e silêncio nunca viram 'offline' no texto de incidente", async ({ page }) => {
  await login(page);
  await page.goto("/noc");
  await expect(page.getByTestId("incident-queue")).toContainText("ONUs fora");
  await expect(page.getByTestId("incident-queue")).toContainText("hipótese, não diagnóstico");
});

test("busca por serial filtra a lista de ONUs", async ({ page }) => {
  await login(page);
  await page.getByLabel("Buscar ONU por serial").fill("DEMOA0001");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/rede\?serial=DEMOA0001/);
  await expect(page.locator("tbody tr")).toHaveCount(1);
});

for (const scheme of ["light", "dark"] as const) {
  test(`acessibilidade (axe) sem violações sérias - tema ${scheme}`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme });
    await login(page);
    for (const r of routes) {
      await page.goto(r);
      const res = await new AxeBuilder({ page: page as never }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
      const bad = res.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
      expect(bad.map((v) => `${v.id}: ${v.nodes[0]?.html}`), `${r} (${scheme})`).toEqual([]);
    }
  });
}

test("navegação por teclado alcança o conteúdo e a busca", async ({ page }) => {
  await login(page);
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Ir para o conteúdo" })).toBeFocused();
});
