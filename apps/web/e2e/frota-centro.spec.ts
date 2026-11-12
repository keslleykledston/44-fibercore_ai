import AxeBuilder from "@axe-core/playwright";
import { createDecipheriv, createECDH, createHash, hkdfSync, randomBytes } from "node:crypto";
import { readFileSync } from "node:fs";
import { expect, test, type APIRequestContext, type Page, type Request } from "@playwright/test";
import { API_URL, EMAIL, login, PASSWORD } from "./helpers";

// Centro de OLT (ADR-0046), contra a stack real: cadastro → passo 2 (a conexão selada no navegador) → o EDGE SIMULADO pelo teste a abre, aplica com `awaiting_local_trust` e informa a confiança → prontidão,
// comando `fibercore-edge managed-trust`, credencial, edição que rebaixa a confiança, Telnet só inventário, sem JavaScript e axe. Precisa de E2E_EDGE_CREDS_FILE e das flags `fleet_provision` e `fleet_secrets` ligadas.
const SUFFIX = String(Date.now()).slice(-6);
const ADDR = "10.99.8.7";
const HK = "SHA256:" + createHash("sha256").update(`host-${SUFFIX}`).digest("base64").replace(/=+$/, "");
const PW = `Senh@-Centro-${SUFFIX}-ç`;
const USER = `adm-c-${SUFFIX}`;
const creds = () => (process.env.E2E_EDGE_CREDS_FILE ? (JSON.parse(readFileSync(process.env.E2E_EDGE_CREDS_FILE, "utf8")) as { client_id: string; client_secret: string }) : null);
const b64u = (b: Buffer) => b.toString("base64url");
const unb64u = (s: string) => Buffer.from(s, "base64url");

async function token(request: APIRequestContext, body: Record<string, string>, path: string) {
  const r = await request.post(`${API_URL}${path}`, { data: body });
  expect(r.status()).toBe(200);
  return { Authorization: `Bearer ${(await r.json()).access_token as string}` };
}
function newEdgeKey() {
  const ecdh = createECDH("prime256v1");
  ecdh.generateKeys();
  const point = ecdh.getPublicKey();
  const digest = createHash("sha256").update(point).digest("hex");
  return { ecdh, pub: b64u(point), keyId: digest.slice(0, 16), fingerprint: (digest.slice(0, 32).match(/.{4}/g) as string[]).join("-") };
}
function openBlob(edge: ReturnType<typeof newEdgeKey>, sealed: string, aad: string, keyId: string): string {
  const blob = unb64u(sealed);
  const shared = edge.ecdh.computeSecret(blob.subarray(1, 66));
  const key = Buffer.from(hkdfSync("sha256", shared, Buffer.alloc(0), Buffer.from(`fibercore-seal-v1|${keyId}`), 32));
  const d = createDecipheriv("aes-256-gcm", key, blob.subarray(66, 78));
  d.setAAD(Buffer.from(aad));
  d.setAuthTag(blob.subarray(blob.length - 16));
  return Buffer.concat([d.update(blob.subarray(78, blob.length - 16)), d.final()]).toString("utf8");
}

/** O Edge de teste: chave P-256 própria, publicada e CONFIRMADA pela pessoa (aqui pela API, como o cartão faz). Devolve o que o Edge e o teste precisam. */
async function prepareEdge(request: APIRequestContext) {
  const edgeH = await token(request, creds()!, "/v1/auth/service-token");
  const adminH = await token(request, { email: EMAIL, password: PASSWORD }, "/v1/auth/token");
  const edge = newEdgeKey();
  expect((await request.post(`${API_URL}/v1/edge/seal-key`, { headers: edgeH, data: { public_key: edge.pub } })).status()).toBe(200);
  const edges = (await (await request.get(`${API_URL}/v1/edges`, { headers: adminH })).json()) as { id: string }[];
  const edgeId = edges[0].id;
  const conf = await request.post(`${API_URL}/v1/fleet/edges/${edgeId}/seal-key/confirm`, { headers: adminH, data: { key_id: edge.keyId, fingerprint: edge.fingerprint } });
  expect(conf.status(), await conf.text()).toBe(200);
  const k = (await (await request.get(`${API_URL}/v1/fleet/edges/${edgeId}/seal-key`, { headers: adminH })).json()) as { tenant_id: string };
  return { edge, edgeH, adminH, edgeId, tenantId: k.tenant_id };
}
/** Um envelope só com o FORMATO certo (versão 1, ponto P-256 real, nonce e tag): a API valida o formato antes de recusar o Telnet; quem abre é o Edge e este nunca o recebe. */
function formatOnlyBlob(): string {
  const e = createECDH("prime256v1");
  e.generateKeys();
  return b64u(Buffer.concat([Buffer.from([1]), e.getPublicKey(), randomBytes(12), randomBytes(17)]));
}
const aadOf = (e: { tenantId: string; edgeId: string }, name: string, kind: string, d: { id: string; key_id: string; expires_at: number }) =>
  ["fibercore-seal-v1", e.tenantId, e.edgeId, name, kind, d.id, d.key_id, String(d.expires_at)].join("\n");

async function register(page: Page, name: string, o: { protocol: "ssh" | "telnet"; address?: string; hostKey?: string }) {
  await page.goto("/rede/frota");
  const form = page.getByTestId("frota-cadastro");
  await form.getByLabel("Nome da OLT").fill(name);
  if (o.address) await form.getByLabel("Endereço de gerência (opcional)").fill(o.address);
  await form.getByLabel("Protocolo de acesso").selectOption(o.protocol);
  if (o.hostKey) await form.getByLabel("Impressão digital do host SSH").fill(o.hostKey);
  return form;
}
const idOf = (page: Page) => page.url().match(/frota\/([0-9a-f-]{36})/)![1];

test("centro de OLT: cadastro → conexão selada no navegador → Edge simulado aplica e confirma → prontidão em cada estágio, comando de confiança, credencial e edição que rebaixa", async ({ page, request }) => {
  test.skip(!creds(), "defina E2E_EDGE_CREDS_FILE (seed_demo.py/scripts/e2e.sh) e ligue as flags fleet_provision e fleet_secrets");
  const E = await prepareEdge(request);
  const sent: { url: string; method: string; body: string | null; headers: string }[] = [];
  const consoleLines: string[] = [];
  page.on("request", (r: Request) => sent.push({ url: r.url(), method: r.method(), body: r.postData(), headers: JSON.stringify(r.headers()) }));
  page.on("console", (m) => consoleLines.push(`${m.type()}: ${m.text()}`));
  page.on("pageerror", (e) => consoleLines.push(`pageerror: ${e.message}`));

  await login(page);
  const name = `E2E-CTR-${SUFFIX}`;
  const form = await register(page, name, { protocol: "ssh", address: ADDR, hostKey: HK });
  await expect(form.getByLabel("Porta de acesso")).toHaveValue("22");                              // o preset acompanha o protocolo
  await form.getByLabel("Protocolo de acesso").selectOption("telnet");
  await expect(form.getByLabel("Porta de acesso")).toHaveValue("23");
  await expect(page.getByTestId("frota-telnet-aviso")).toContainText("Não há campo de senha");
  await expect(form.getByLabel("Impressão digital do host SSH")).toHaveCount(0);                    // Telnet não tem impressão digital
  await form.getByLabel("Protocolo de acesso").selectOption("ssh");
  await expect(form.getByLabel("Porta de acesso")).toHaveValue("22");
  await form.getByLabel("Impressão digital do host SSH").fill(HK);
  await page.getByTestId("frota-cadastrar-continuar").click();
  await expect(page).toHaveURL(new RegExp(`/rede/frota/[0-9a-f-]{36}\\?ok=oltassistente#passos`));
  const oltId = idOf(page);
  const passos = page.getByTestId("frota-passos");
  await expect(passos).toBeVisible();
  await expect(page.getByTestId("frota-flash")).toContainText("Siga o assistente");
  await expect(page.getByTestId("frota-prontidao-texto")).toHaveText("Cadastrada");
  await expect(page.getByTestId("passo-1")).toContainText("Feito");
  await expect(page.getByTestId("passo-2")).toContainText("Ainda não enviada");

  // o endereço digitado veio do cadastro SÓ pela memória desta página (nunca pela URL nem por armazenamento)
  const addr = page.getByTestId("conn-form").getByLabel("Endereço de gerência da OLT");
  await expect(addr).toHaveValue(ADDR);
  await expect(page.getByTestId("conn-endereco-ajuda")).toContainText("Trazido do cadastro");
  expect(page.url()).not.toContain(ADDR);
  expect(await page.evaluate(() => JSON.stringify({ l: { ...localStorage }, s: { ...sessionStorage } }))).not.toContain(ADDR);
  await expect(page.getByTestId("conn-resumo")).toContainText("SSH · 22");
  await expect(page.getByTestId("conn-resumo")).toContainText(HK);
  await expect(page.getByTestId("conn-resumo")).toContainText("10.99.•.•");

  // envia a conexão: só texto cifrado sai do navegador
  const posted = page.waitForRequest((r) => r.method() === "POST" && r.url().includes(`/bff/frota/olts/${oltId}/credenciais`));
  await page.getByTestId("conn-enviar").click();
  const env = JSON.parse((await posted).postData() ?? "{}") as Record<string, unknown>;
  expect(Object.keys(env).sort()).toEqual(["delivery_id", "expires_at", "key_id", "kind", "sealed"]);
  expect(env.kind).toBe("olt_connection");
  expect(env.key_id).toBe(E.edge.keyId);
  await expect(page.getByTestId("conn-msg")).toContainText("Conexão cifrada e enviada");
  await expect(addr).toHaveValue("");                                                              // o campo é apagado ao enviar
  await expect(page.getByTestId("conn-entregas")).toContainText("Aguardando o Edge");
  await expect(page.getByTestId("passo-2")).toContainText("Aguardando o Edge");

  // o Edge simulado busca, verifica a AAD (com o kind), abre e confere o texto do ADR D4
  const next = await request.get(`${API_URL}/v1/edge/secret-deliveries/next`, { headers: E.edgeH });
  expect(next.status()).toBe(200);
  const d = await next.json();
  expect(d.kind).toBe("olt_connection");
  expect(d.sealed).toBe(env.sealed);
  expect(JSON.parse(openBlob(E.edge, d.sealed, aadOf(E, name, "olt_connection", d), d.key_id))).toEqual({
    kind: "olt_connection", action: "set", address: ADDR, port: 22, protocol: "ssh", vendor: "huawei", transport: "cli", snmp_port: 161, host_key_sha256: HK, legacy_ssh: false, ssh_mode: "exec", cloud_id: oltId });
  expect(() => openBlob(E.edge, d.sealed, aadOf(E, name, "ssh_login", d), d.key_id)).toThrow();   // o kind faz parte da AAD
  // aplicado, mas aguardando a confiança local
  expect((await request.post(`${API_URL}/v1/edge/secret-deliveries/${d.id}/result`, { headers: E.edgeH, data: { lease_token: d.lease_token, outcome: "applied", code: "awaiting_local_trust" } })).status()).toBe(204);
  await page.getByTestId("conn-atualizar").click();
  await expect(page.getByTestId("conn-confianca")).toBeVisible();
  await expect(page.getByTestId("conn-comando")).toHaveText(`fibercore-edge managed-trust ${name}`);
  await expect(page.getByTestId("passos-comando")).toContainText(`fibercore-edge managed-trust ${name}`);
  await expect(page.getByTestId("conn-codigo").first()).toContainText("managed-trust");
  await page.reload();
  await expect(page.getByTestId("frota-prontidao-detalhe")).toHaveAttribute("data-stage", "awaiting_trust");
  await expect(page.getByTestId("frota-prontidao-texto")).toHaveText("Aguardando confirmação no Edge");
  await expect(page.getByTestId("passo-2")).toContainText("aguardando confirmação no Edge");
  await expect(page.getByTestId("passo-4")).toContainText("Ainda não testada");
  await expect(page.locator("body")).not.toContainText(ADDR);                                       // o endereço inteiro nunca volta na tela

  // o administrador do Edge confirmou o host: o Edge informa
  const st = await request.post(`${API_URL}/v1/edge/managed-olts/state`, { headers: E.edgeH, data: { items: [{ cloud_id: oltId, state: "trusted" }] } });
  expect(await st.json()).toEqual({ updated: 1, ignored: 0 });
  await page.reload();
  await expect(page.getByTestId("frota-prontidao-detalhe")).toHaveAttribute("data-stage", "trusted");
  await expect(page.getByTestId("passo-2")).toContainText("confirmada no Edge");
  await expect(page.getByTestId("passos-comando")).toHaveCount(0);

  // passo 3: a credencial (cartão existente) e o Edge simulado a aplica
  const cred = page.getByTestId("cred-form");
  await expect(cred).toBeVisible();
  const pw = cred.locator("input[type=password]");
  await pw.nth(0).fill(USER);
  await pw.nth(1).fill(PW);
  await page.getByTestId("cred-enviar").click();
  await expect(page.getByTestId("cred-msg")).toContainText("Credencial cifrada e enviada");
  const n2 = await (await request.get(`${API_URL}/v1/edge/secret-deliveries/next`, { headers: E.edgeH })).json();
  expect(n2.kind).toBe("ssh_login");
  expect(JSON.parse(openBlob(E.edge, n2.sealed, aadOf(E, name, "ssh_login", n2), n2.key_id))).toEqual({ kind: "ssh_login", username: USER, password: PW });
  expect((await request.post(`${API_URL}/v1/edge/secret-deliveries/${n2.id}/result`, { headers: E.edgeH, data: { lease_token: n2.lease_token, outcome: "applied" } })).status()).toBe(204);
  await page.reload();
  await expect(page.getByTestId("frota-prontidao-detalhe")).toHaveAttribute("data-stage", "credential_applied");
  await expect(page.getByTestId("passo-3")).toContainText("Credencial aplicada");
  await expect(page.getByTestId("passo-4")).toContainText("Pronta para testar");

  // a11y do assistente completo e alvos de toque
  const ax = await new AxeBuilder({ page: page as never }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  expect(ax.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" || ")}`)).toEqual([]);
  for (const el of await page.getByTestId("conn-form").locator("input, button").all()) {
    const box = await el.boundingBox();
    if (box) expect(Math.min(box.width, box.height)).toBeGreaterThanOrEqual(24);
  }

  // editar COMO a OLT é alcançada rebaixa a conexão e a confiança: o assistente volta a pedir a entrega
  await page.getByLabel("Porta de acesso").fill("2200");
  await page.getByTestId("frota-salvar").click();
  await expect(page.getByTestId("frota-flash")).toContainText("OLT atualizada");
  await expect(page.getByTestId("frota-prontidao-detalhe")).toHaveAttribute("data-stage", "registered");
  await expect(page.getByTestId("passo-2")).toContainText("envie de novo");
  await expect(page.getByLabel("Porta de acesso")).toHaveValue("2200");
  // a lista mostra a prontidão da OLT
  await page.goto("/rede/frota");
  await expect(page.getByTestId("frota-olt").filter({ hasText: name }).getByTestId("frota-prontidao")).toHaveAttribute("data-stage", "registered");
  const axList = await new AxeBuilder({ page: page as never }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  expect(axList.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => v.id)).toEqual([]);

  // o endereço e o texto claro NUNCA saíram do navegador em nenhuma requisição, URL, cabeçalho, console ou armazenamento
  expect(sent.filter((r) => r.method === "POST" && r.url.includes("/credenciais")).length).toBeGreaterThanOrEqual(2);
  for (const secret of [ADDR, PW, USER]) {
    const variants = [secret, encodeURIComponent(secret), Buffer.from(secret).toString("base64"), Buffer.from(secret).toString("base64url")];
    for (const r of sent.filter((x) => !x.url.endsWith("/bff/frota/olts") || x.method !== "POST")) for (const v of variants) {   // o cadastro (passo 1) envia o endereço em claro de propósito: ele é do cadastro, não da entrega
      expect(r.url, `${r.method} ${r.url}`).not.toContain(v);
      expect(r.headers).not.toContain(v);
      if (secret !== ADDR) expect(r.body ?? "").not.toContain(v);
      else if (r.url.includes("/credenciais")) expect(r.body ?? "").not.toContain(v);
    }
    for (const line of consoleLines) expect(line).not.toContain(secret);
  }
  expect(consoleLines.filter((l) => /content security policy|refused to (execute|load)/i.test(l)), consoleLines.join("\n")).toEqual([]);
});

test("centro de OLT: depois de recarregar o endereço não volta; a máscara conferida impede erro de digitação; sem JavaScript nada é selável", async ({ page, request, context, browser }) => {
  test.skip(!creds(), "defina E2E_EDGE_CREDS_FILE (seed_demo.py/scripts/e2e.sh) e ligue as flags fleet_provision e fleet_secrets");
  await prepareEdge(request);
  const posts: string[] = [];
  page.on("request", (r) => { if (r.method() === "POST" && r.url().includes("/credenciais")) posts.push(r.url()); });
  await login(page);
  await register(page, `E2E-CTR2-${SUFFIX}`, { protocol: "ssh", address: ADDR, hostKey: HK });
  await page.getByTestId("frota-cadastrar-continuar").click();
  await expect(page).toHaveURL(/#passos/);
  const oltId = idOf(page);
  await page.reload();                                                                               // recarregar perde o rascunho (só memória)
  const addr = page.getByTestId("conn-form").getByLabel("Endereço de gerência da OLT");
  await expect(addr).toHaveValue("");
  await expect(page.getByTestId("conn-endereco-ajuda")).toContainText("digite-o de novo");
  await expect(page.getByTestId("conn-endereco-ajuda")).toContainText("10.99.•.•");
  await page.getByTestId("conn-enviar").click();
  await expect(page.getByTestId("conn-msg")).toContainText("Informe um IP");
  await addr.fill("10.98.8.7");                                                                     // erro de digitação: outra máscara
  await page.getByTestId("conn-enviar").click();
  await expect(page.getByTestId("conn-msg")).toContainText("mesma máscara");
  await addr.fill("olt.example.com");
  await page.getByTestId("conn-enviar").click();
  await expect(page.getByTestId("conn-msg")).toContainText("Informe um IP");
  expect(posts).toHaveLength(0);                                                                    // nada saiu
  // sem JavaScript: o assistente aparece, mas nenhum campo de entrega existe (falha fechada)
  const state = await context.storageState();
  const noJs = await browser.newContext({ javaScriptEnabled: false, storageState: state, baseURL: process.env.WEB_URL ?? "http://127.0.0.1:3000" });
  const p2 = await noJs.newPage();
  await p2.goto(`/rede/frota/${oltId}`);
  await expect(p2.getByTestId("frota-passos")).toBeVisible();
  await expect(p2.getByTestId("conn-sem-js")).toContainText("exige JavaScript");
  await expect(p2.getByTestId("conn-form")).toHaveCount(0);
  await expect(p2.locator("input[type=password]")).toHaveCount(0);
  await noJs.close();
});

test("centro de OLT: Telnet é só inventário (sem senha, sem entrega) e a API recusa pelo BFF", async ({ page, request }) => {
  test.skip(!creds(), "defina E2E_EDGE_CREDS_FILE (seed_demo.py/scripts/e2e.sh) e ligue as flags fleet_provision e fleet_secrets");
  await prepareEdge(request);
  await login(page);
  const name = `E2E-TEL-${SUFFIX}`;
  const form = await register(page, name, { protocol: "telnet", address: "10.99.7.6" });
  await expect(form.getByLabel("Porta de acesso")).toHaveValue("23");
  await page.getByTestId("frota-cadastrar-continuar").click();
  await expect(page).toHaveURL(/#passos/);
  const oltId = idOf(page);
  await expect(page.getByTestId("passos-telnet")).toContainText("Telnet é só inventário");
  await expect(page.getByTestId("frota-prontidao-texto")).toHaveText("Aguardando suporte a Telnet (só cadastro)");
  for (const n of [2, 3, 4]) await expect(page.getByTestId(`passo-${n}`)).toContainText("Aguardando suporte a Telnet");
  await expect(page.locator("input[type=password]")).toHaveCount(0);
  await expect(page.getByTestId("conn-form")).toHaveCount(0);
  await expect(page.getByTestId("cred-envio")).toHaveCount(0);
  await expect(page.getByTestId("cred-telnet")).toBeVisible();
  const ax = await new AxeBuilder({ page: page as never }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  expect(ax.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => v.id)).toEqual([]);
  // na lista: sem cadeia, só a frase
  await page.goto("/rede/frota");
  await expect(page.getByTestId("frota-olt").filter({ hasText: name })).toContainText("Aguardando suporte a Telnet (só cadastro)");
  // pelo BFF, qualquer kind é recusado pelo servidor (nada é enfileirado)
  await page.goto(`/rede/frota/${oltId}`);
  const origin = new URL(page.url()).origin;
  for (const kind of ["olt_connection", "ssh_login", "snmp_community"]) {
    const body = { delivery_id: crypto.randomUUID(), kind, key_id: "0123456789abcdef", expires_at: Math.floor(Date.now() / 1000) + 600, sealed: formatOnlyBlob() };
    const r = await page.request.post(`${origin}/bff/frota/olts/${oltId}/credenciais`, { data: body, headers: { origin } });
    expect(r.status(), kind).toBe(422);
    expect((await r.json()).detail).toBe("protocol_not_supported");
  }
  // trocar para SSH pela edição devolve a porta 22 e liga a cadeia
  await page.getByLabel("Protocolo de acesso").selectOption("ssh");
  await expect(page.getByLabel("Porta de acesso")).toHaveValue("22");
  await page.getByLabel("Impressão digital do host SSH").fill(HK);
  await page.getByTestId("frota-salvar").click();
  await expect(page.getByTestId("frota-flash")).toContainText("OLT atualizada");
  await expect(page.getByTestId("frota-prontidao-detalhe")).toHaveAttribute("data-stage", "registered");
  await expect(page.getByTestId("conn-form")).toBeVisible();
});
