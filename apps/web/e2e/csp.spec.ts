import { expect, test, type Page } from "@playwright/test";
import { API_URL, EMAIL, login, PASSWORD } from "./helpers";

// CSP com nonce (ADR-0042) no navegador real, na stack real com o seed sintético.
//  - `WEB_URL` (modo padrão, report-only): páginas principais sem NENHUMA violação (console + evento securitypolicyviolation).
//  - `CSP_ENFORCE_URL` (outro `next start` com FIBERCORE_CSP_MODE=enforce): as mesmas páginas sem violação E prova de que script inline sem nonce é bloqueado.
// Sem `CSP_ENFORCE_URL` os testes de enforce são pulados (a stack efêmera sobe as duas instâncias; ver docs/wiki/adr/ADR-0042).
const ENFORCE_URL = process.env.CSP_ENFORCE_URL;
const VIOLATION_TEXT = /Content Security Policy|Refused to|violates the following/i;

async function instrument(page: Page) {
  const consoleHits: string[] = [];
  page.on("console", (m) => { if (VIOLATION_TEXT.test(m.text())) consoleHits.push(`${m.type()}: ${m.text()}`); });
  page.on("pageerror", (e) => { if (VIOLATION_TEXT.test(e.message)) consoleHits.push(`pageerror: ${e.message}`); });
  await page.addInitScript(() => {
    (window as unknown as { __csp: string[] }).__csp = [];
    document.addEventListener("securitypolicyviolation", (e) => (window as unknown as { __csp: string[] }).__csp.push(`${e.disposition} ${e.violatedDirective} ${e.blockedURI} ${(e.sample || "").slice(0, 60)}`));
  });
  const events = () => page.evaluate(() => (window as unknown as { __csp?: string[] }).__csp ?? []);
  return { consoleHits, events };
}

const onuId = async (request: import("@playwright/test").APIRequestContext) => {
  const tok = (await (await request.post(`${API_URL}/v1/auth/token`, { data: { email: EMAIL, password: PASSWORD } })).json()).access_token as string;
  const onus = (await (await request.get(`${API_URL}/v1/onus?serial=DEMOA0002`, { headers: { Authorization: `Bearer ${tok}` } })).json()) as { id: string }[];
  return onus[0].id;
};

const PAGES = ["/", "/rede", "/rede/offline", "/rede/catalogo", "/rede/frota", "/rede/conhecimento", "/rede/homologacao", "/rede/perfis", "/rede/pendentes", "/noc", "/dispositivos",
  "/dispositivos/edges", "/dispositivos/capacidades", "/operacoes", "/assinantes", "/ajuda", "/conta/seguranca", "/administracao/equipe", "/administracao/membros", "/administracao/papeis", "/administracao/modulos"];

async function crawl(page: Page, request: import("@playwright/test").APIRequestContext) {
  const probe = await instrument(page);
  const seen: string[] = [];
  const visit = async (path: string) => {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    seen.push(...(await probe.events()).map((e) => `${path} :: ${e}`));
  };
  // a página de login também é documento HTML com CSP (antes o middleware a ignorava)
  await visit("/login");
  await login(page);
  for (const p of PAGES) await visit(p);
  const id = await onuId(request);
  await visit(`/rede/onu/${id}`);                 // régua óptica (atributos style) + miniatura/LEDs
  await visit(`/rede/onu/${id}/diagnostico`);
  // navegação do lado do cliente (fetch RSC passa pelo middleware): clica num link do menu sem recarregar o documento
  await page.goto("/");
  await page.locator('nav[aria-label="Principal"] a[href="/noc"]').first().click();
  await page.waitForLoadState("networkidle");
  seen.push(...(await probe.events()).map((e) => `(rsc) :: ${e}`));
  return { seen, consoleHits: probe.consoleHits };
}

test("modo padrão (report-only): cabeçalho Report-Only com nonce novo a cada requisição e NENHUMA violação nas páginas principais", async ({ page, request, baseURL }) => {
  const a = await request.get(`${baseURL}/login`);
  const b = await request.get(`${baseURL}/login`);
  const h = a.headers();
  const mode = process.env.FIBERCORE_CSP_MODE_EXPECTED ?? "report-only";   // a stack de teste padrão não define a variável
  const name = mode === "enforce" ? "content-security-policy" : "content-security-policy-report-only";
  expect(h[name], `cabeçalho ${name}`).toBeTruthy();
  if (mode !== "enforce") expect(h["content-security-policy"]).toBeUndefined();
  const nonce = (r: typeof a) => /'nonce-([^']+)'/.exec(r.headers()[name])![1];
  expect(nonce(a)).not.toBe(nonce(b));
  const html = await a.text();
  const scripts = [...html.matchAll(/<script\b([^>]*)>/g)].map((m) => m[1]);
  expect(scripts.length).toBeGreaterThan(3);
  expect(scripts.filter((s) => !s.includes(`nonce="${nonce(a)}"`)), "scripts sem o nonce desta resposta").toEqual([]);
  expect(html).not.toMatch(/<style\b/i);          // nenhum <style> de elemento: só link para /_next/static
  const { seen, consoleHits } = await crawl(page, request);
  expect(seen, "violações de CSP (securitypolicyviolation)").toEqual([]);
  expect(consoleHits, "mensagens de violação no console").toEqual([]);
});

// O middleware passou a cobrir /login e a montar os cabeçalhos da requisição (nonce) junto com a renovação de sessão: regressão da renovação.
test("renovação de sessão com CSP: /login não consome o refresh; rota protegida renova (inclusive 2 requisições simultâneas) e traz CSP; sem cair no login", async ({ page, context }) => {
  await login(page);
  const refresh = async () => (await context.cookies()).find((c) => c.name === "fc_refresh")!.value;
  const r0 = await refresh();
  await context.clearCookies({ name: "fc_token" });             // access token expirado, refresh válido
  const rl = await page.goto("/login");
  expect(rl!.headers()["content-security-policy-report-only"] ?? rl!.headers()["content-security-policy"], "CSP também em /login").toContain("'nonce-");
  expect(await refresh(), "/login não pode rotacionar o refresh").toBe(r0);
  expect((await context.cookies()).find((c) => c.name === "fc_token"), "/login não cria sessão nova").toBeUndefined();
  const both = await Promise.all([context.request.get("/rede", { maxRedirects: 0 }), context.request.get("/rede", { maxRedirects: 0 })]);   // mesmo cookie, em paralelo: UMA rotação compartilhada
  expect(both.map((r) => r.status()), "nenhuma das duas pode ser redirecionada ao login").toEqual([200, 200]);
  const html = await both[0].text();
  const hdr = both[0].headers()["content-security-policy-report-only"] ?? both[0].headers()["content-security-policy"];
  expect(hdr).toContain("'nonce-");
  expect(html, "o HTML renderizado tem o nonce da PRÓPRIA resposta").toContain(`nonce="${/'nonce-([^']+)'/.exec(hdr)![1]}"`);
  expect(await refresh(), "o refresh rotacionou").not.toBe(r0);
  await page.goto("/rede");
  await expect(page).toHaveURL(/\/rede$/);
});

test.describe("enforce", () => {
  test.skip(!ENFORCE_URL, "CSP_ENFORCE_URL não definido: suba um segundo next start com FIBERCORE_CSP_MODE=enforce");
  test.use({ baseURL: ENFORCE_URL });

  test("cabeçalho Content-Security-Policy (e não Report-Only), sem unsafe-inline em script/estilo de elemento, e o app inteiro funciona sem violação", async ({ page, request }) => {
    const r = await request.get(`${ENFORCE_URL}/login`);
    const csp = r.headers()["content-security-policy"];
    expect(csp).toBeTruthy();
    expect(r.headers()["content-security-policy-report-only"]).toBeUndefined();
    const d = Object.fromEntries(csp.split("; ").map((x) => [x.split(" ")[0], x.split(" ").slice(1).join(" ")]));
    expect(d["script-src"]).toMatch(/^'self' 'nonce-[^']+' 'strict-dynamic'$/);
    expect(d["style-src"]).toMatch(/^'self' 'nonce-[^']+'$/);
    const { seen, consoleHits } = await crawl(page, request);
    expect(seen, "violações de CSP (securitypolicyviolation)").toEqual([]);
    expect(consoleHits, "mensagens de violação no console").toEqual([]);
  });

  test("o script inline do tema (com nonce) roda: tema salvo é aplicado antes da hidratação", async ({ page }) => {
    await page.addInitScript(() => { try { localStorage.setItem("fc-theme", "dark"); } catch { /* ignore */ } });
    await page.goto("/login");
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  });

  // Simula uma injeção de HTML (o que um XSS refletido/armazenado faria): o corpo de /login é reescrito NO TRÂNSITO, mantendo os cabeçalhos (inclusive a CSP e o nonce)
  // da resposta real. Scripts inseridos pelo parser são o vetor que a CSP existe para barrar. (Script criado por DOM de dentro de código já confiável é permitido
  // por 'strict-dynamic' por desenho: a defesa é não deixar o atacante chegar a executar código; ver ADR-0042.)
  async function loginComHtmlInjetado(page: Page, inject: (nonce: string) => string) {
    await page.route(/\/login$/, async (route) => {
      const resp = await route.fetch();
      const nonce = /'nonce-([^']+)'/.exec(resp.headers()["content-security-policy"] ?? "")![1];
      await route.fulfill({ response: resp, body: (await resp.text()).replace("</body>", `${inject(nonce)}</body>`) });
    });
    const probe = await instrument(page);
    await page.goto("/login");
    return probe;
  }
  const flag = (page: Page, k: string) => page.evaluate((key) => (window as unknown as Record<string, unknown>)[key] ?? null, k);

  test("script inline SEM nonce injetado no HTML é bloqueado; o mesmo script com o nonce da resposta executa (a política é o que decide)", async ({ page }) => {
    const probe = await loginComHtmlInjetado(page, (n) => `<script>window.__pwn='executou'</script><script nonce="${n}">window.__ok='executou'</script>`);
    expect(await flag(page, "__pwn"), "script sem nonce NÃO pode executar").toBeNull();
    expect(await flag(page, "__ok"), "script com o nonce da resposta executa").toBe("executou");
    expect((await probe.events()).some((e) => /^enforce script-src-elem inline/.test(e)), "evento securitypolicyviolation em enforce").toBe(true);
    expect(probe.consoleHits.some((c) => /Refused to execute inline script/.test(c))).toBe(true);
  });

  test("outros vetores injetados também caem: onerror/onclick inline, javascript: URL, <style> sem nonce e eval em script com nonce", async ({ page }) => {
    await loginComHtmlInjetado(page, (n) => `
      <img id="pwn-img" src="/nao-existe.png" onerror="window.__onerror='executou'">
      <button id="pwn-btn" type="button" onclick="window.__onclick='executou'">x</button>
      <a id="pwn-a" href="javascript:window.__jsurl='executou'">y</a>
      <div id="pwn-marker">m</div><style>#pwn-marker{display:none}</style>
      <div id="attr-marker" style="display:none">a</div>
      <script nonce="${n}">try{eval("window.__eval='executou'")}catch(e){window.__evalBloqueado=e.name}</script>`);
    await page.locator("#pwn-btn").dispatchEvent("click");
    await page.locator("#pwn-a").dispatchEvent("click");
    await page.waitForTimeout(300);
    expect(await flag(page, "__onerror"), "onerror inline").toBeNull();
    expect(await flag(page, "__onclick"), "onclick inline").toBeNull();
    expect(await flag(page, "__jsurl"), "javascript: URL").toBeNull();
    expect(await flag(page, "__eval"), "eval").toBeNull();
    expect(await flag(page, "__evalBloqueado"), "eval lança EvalError").toBe("EvalError");
    expect(await page.locator("#pwn-marker").evaluate((e) => getComputedStyle(e).display), "<style> sem nonce não aplica").not.toBe("none");
    // o que a política permite DE PROPÓSITO (restante documentado): atributo style= (style-src-attr 'unsafe-inline')
    expect(await page.locator("#attr-marker").evaluate((e) => getComputedStyle(e).display), "atributo style= segue valendo").toBe("none");
  });

  test("login real funciona em enforce (formulário POST same-origin, redirecionamento e hidratação)", async ({ page }) => {
    await login(page);
    await expect(page).toHaveURL(/\/$/);
  });
});
