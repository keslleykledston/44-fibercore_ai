import AxeBuilder from "@axe-core/playwright";
import { createDecipheriv, createECDH, createHash, hkdfSync } from "node:crypto";
import { readFileSync } from "node:fs";
import { expect, test, type APIRequestContext, type Page, type Request } from "@playwright/test";
import { API_URL, EMAIL, login, PASSWORD } from "./helpers";

// Credenciais da OLT pela tela (ADR-0045), contra a stack real: o navegador sela com a chave do Edge; o BFF e a API só veem texto cifrado.
// Aqui o teste faz o papel do EDGE (conta de serviço do seed): publica uma chave P-256, busca a entrega e a ABRE com Node crypto (implementação independente do WebCrypto do navegador).
// Precisa de E2E_EDGE_CREDS_FILE (JSON {client_id, client_secret} da conta de serviço do Edge do seed; scripts/e2e.sh e seed_demo.py cuidam disso) e da flag `fleet_secrets` ligada.
const SUFFIX = String(Date.now()).slice(-6);
const PW = `Senh@-Teste-${SUFFIX}-ç`;
const USER = `adm-${SUFFIX}`;
const COMM = `comm-${SUFFIX}-xyz`;
const creds = () => (process.env.E2E_EDGE_CREDS_FILE ? (JSON.parse(readFileSync(process.env.E2E_EDGE_CREDS_FILE, "utf8")) as { client_id: string; client_secret: string }) : null);

const b64u = (b: Buffer) => b.toString("base64url");
const unb64u = (s: string) => Buffer.from(s, "base64url");

async function token(request: APIRequestContext, body: Record<string, string>, path: string) {
  const r = await request.post(`${API_URL}${path}`, { data: body });
  expect(r.status()).toBe(200);
  return { Authorization: `Bearer ${(await r.json()).access_token as string}` };
}
const adminHeaders = (request: APIRequestContext) => token(request, { email: EMAIL, password: PASSWORD }, "/v1/auth/token");

/** O Edge de teste: chave P-256 própria (a privada fica só neste processo) e as chamadas que o Edge real faz. */
function newEdgeKey() {
  const ecdh = createECDH("prime256v1");
  ecdh.generateKeys();
  const point = ecdh.getPublicKey();   // 65 bytes, não comprimido
  const digest = createHash("sha256").update(point).digest("hex");
  return { ecdh, point, pub: b64u(point), keyId: digest.slice(0, 16), fingerprint: (digest.slice(0, 32).match(/.{4}/g) as string[]).join("-") };
}
function openBlob(edge: ReturnType<typeof newEdgeKey>, sealed: string, aad: string, keyId: string): string {
  const blob = unb64u(sealed);
  expect(blob[0]).toBe(1);
  const shared = edge.ecdh.computeSecret(blob.subarray(1, 66));
  const key = Buffer.from(hkdfSync("sha256", shared, Buffer.alloc(0), Buffer.from(`fibercore-seal-v1|${keyId}`), 32));
  const d = createDecipheriv("aes-256-gcm", key, blob.subarray(66, 78));
  d.setAAD(Buffer.from(aad));
  d.setAuthTag(blob.subarray(blob.length - 16));
  return Buffer.concat([d.update(blob.subarray(78, blob.length - 16)), d.final()]).toString("utf8");
}

async function registerOltAndOpenCard(page: Page, name: string) {
  await page.goto("/rede/frota");
  const form = page.getByTestId("frota-cadastro");
  await form.getByLabel("Nome da OLT").fill(name);
  await page.getByTestId("frota-cadastrar-credenciais").click();
  await expect(page).toHaveURL(new RegExp(`/rede/frota/[0-9a-f-]{36}.*#credenciais`));
  await expect(page.getByTestId("frota-flash")).toContainText("Configure agora as credenciais");
  const m = page.url().match(/frota\/([0-9a-f-]{36})/)!;
  return m[1];
}

test("credenciais: o texto claro nunca sai do navegador; o Edge de teste abre o blob; campos apagados; estados e códigos em português; a11y e CSP", async ({ page, request, context, browser }) => {
  test.skip(!creds(), "defina E2E_EDGE_CREDS_FILE (seed_demo.py/scripts/e2e.sh) e ligue a flag fleet_secrets");
  const edgeCreds = creds()!;
  const edgeH = await token(request, edgeCreds, "/v1/auth/service-token");   // service-token usa {client_id, client_secret}
  const edge = newEdgeKey();
  expect((await request.post(`${API_URL}/v1/edge/seal-key`, { headers: edgeH, data: { public_key: edge.pub } })).status()).toBe(200);

  // tudo o que o navegador envia, e tudo o que ele escreve no console, é vigiado desde o início
  const sent: { url: string; method: string; body: string | null; headers: string }[] = [];
  const consoleLines: string[] = [];
  page.on("request", (r: Request) => sent.push({ url: r.url(), method: r.method(), body: r.postData(), headers: JSON.stringify(r.headers()) }));
  page.on("console", (m) => consoleLines.push(`${m.type()}: ${m.text()}`));
  page.on("pageerror", (e) => consoleLines.push(`pageerror: ${e.message}`));

  await login(page);
  const name = `E2E-CRED-${SUFFIX}`;
  const oltId = await registerOltAndOpenCard(page, name);
  const card = page.getByTestId("frota-credenciais");
  await expect(card).toBeVisible();
  // avisos exigidos: testar a conexão depois, v3 não suportado, credentials_file pelo administrador do Edge
  await expect(page.getByTestId("cred-avisos")).toContainText("Testar conexão");
  await expect(page.getByTestId("cred-avisos")).toContainText("SNMP v3 não é suportado");
  await expect(page.getByTestId("cred-avisos")).toContainText("credentials_file");
  // chave pendente: a impressão digital é a do Edge de teste, recalculada no navegador, e o envio está bloqueado até confirmar
  await expect(page.getByTestId("cred-chave-estado")).toContainText("Aguardando a sua confirmação");
  await expect(page.getByTestId("cred-fingerprint")).toHaveText(edge.fingerprint);
  await expect(page.getByTestId("cred-fp-local")).toContainText("confere");
  await expect(page.getByTestId("cred-bloqueado")).toBeVisible();
  await expect(page.locator("input[type=password]")).toHaveCount(0);
  // a impressão digital errada não confirma; a certa (digitada em minúsculas e sem traços) confirma
  await page.getByLabel("Digite a impressão digital mostrada no servidor do Edge").fill("0000-0000-0000-0000-0000-0000-0000-0000");
  await page.getByTestId("cred-confirmar-btn").click();
  await expect(page.getByTestId("frota-flash")).toContainText("não confere");
  await page.getByLabel("Digite a impressão digital mostrada no servidor do Edge").fill(edge.fingerprint.replaceAll("-", "").toUpperCase());
  await page.getByTestId("cred-confirmar-btn").click();
  await expect(page.getByTestId("frota-flash")).toContainText("Chave do Edge confirmada");
  await expect(page.getByTestId("cred-chave-estado")).toContainText("Confirmada");

  // o formulário só existe com JavaScript e WebCrypto: campos type=password, sem autocomplete
  const form = page.getByTestId("cred-form");
  await expect(form).toBeVisible();
  const passwordInputs = form.locator("input[type=password]");
  await expect(passwordInputs).toHaveCount(2);
  for (const i of [0, 1]) {
    await expect(passwordInputs.nth(i)).not.toHaveAttribute("name", /.+/);               // nada seria serializado num envio nativo
    expect(await passwordInputs.nth(i).getAttribute("autocomplete")).toMatch(/^(off|new-password)$/);
  }
  expect(await page.locator("form[data-testid=cred-form]").getAttribute("action")).toBeNull();
  await page.setViewportSize({ width: 1280, height: 2600 });   // a análise vê a página inteira: um campo na borda da janela de 720 px não conta como "parcialmente coberto"
  const axeForm = await new AxeBuilder({ page: page as never }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  expect(axeForm.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" || ")}`)).toEqual([]);
  for (const el of await form.locator("input, button").all()) {   // alvos >= 24 px (WCAG 2.2 AA)
    const box = await el.boundingBox();
    if (box) expect(Math.min(box.width, box.height), await el.evaluate((e) => e.outerHTML.slice(0, 80))).toBeGreaterThanOrEqual(24);
  }
  // validação local: vazio é recusado sem enviar nada
  const before = sent.length;
  await page.getByTestId("cred-enviar").click();
  await expect(page.getByTestId("cred-msg")).toContainText("obrigatório");
  expect(sent.slice(before).filter((r) => r.url.includes("/credenciais") && r.method === "POST")).toHaveLength(0);

  // envio de login e senha
  await passwordInputs.nth(0).fill(USER);
  await passwordInputs.nth(1).fill(PW);
  const bodyOf = page.waitForRequest((r) => r.method() === "POST" && r.url().includes(`/bff/frota/olts/${oltId}/credenciais`));
  await page.getByTestId("cred-enviar").click();
  const posted = await bodyOf;
  const postedBody = posted.postData() ?? "";
  const env = JSON.parse(postedBody) as Record<string, unknown>;
  expect(Object.keys(env).sort()).toEqual(["delivery_id", "expires_at", "key_id", "kind", "sealed"]);
  expect(env.kind).toBe("ssh_login");
  expect(env.key_id).toBe(edge.keyId);
  const blob = unb64u(env.sealed as string);
  expect(env.sealed).toMatch(/^[A-Za-z0-9_-]+$/);
  expect((env.sealed as string).length).toBeLessThanOrEqual(2048);
  expect(blob[0]).toBe(1);                              // versão
  expect(blob[1]).toBe(4);                              // efêmera: ponto não comprimido
  expect(blob.length).toBeGreaterThanOrEqual(1 + 65 + 12 + 16 + 1);
  await expect(page.getByTestId("cred-msg")).toContainText("Credencial cifrada e enviada");
  // campos apagados após enviar
  await expect(passwordInputs.nth(0)).toHaveValue("");
  await expect(passwordInputs.nth(1)).toHaveValue("");
  await expect(page.getByTestId("cred-entregas")).toContainText("Login e senha (SSH)");
  await expect(page.getByTestId("cred-entregas")).toContainText("Aguardando o Edge");

  // o Edge de teste busca, abre com a chave privada e confere o conteúdo e a AAD
  const ah = await adminHeaders(request);
  const olt = (await (await request.get(`${API_URL}/v1/fleet/olts/${oltId}`, { headers: ah })).json()) as { edge: { id: string } };
  const tenant = (await (await request.get(`${API_URL}/v1/fleet/edges/${olt.edge.id}/seal-key`, { headers: ah })).json()) as { tenant_id: string; edge_id: string };
  const next = await request.get(`${API_URL}/v1/edge/secret-deliveries/next`, { headers: edgeH });
  expect(next.status()).toBe(200);
  const d = await next.json();
  expect(d.sealed).toBe(env.sealed);
  const aad = ["fibercore-seal-v1", tenant.tenant_id, tenant.edge_id, name, "ssh_login", d.id, d.key_id, String(d.expires_at)].join("\n");
  expect(JSON.parse(openBlob(edge, d.sealed, aad, d.key_id))).toEqual({ kind: "ssh_login", username: USER, password: PW });
  expect((await request.post(`${API_URL}/v1/edge/secret-deliveries/${d.id}/result`, { headers: edgeH, data: { lease_token: d.lease_token, outcome: "applied" } })).status()).toBe(204);
  await page.getByTestId("cred-atualizar").click();
  await expect(page.getByTestId("cred-estado").first()).toHaveText("Aplicada");

  // community SNMP: segunda entrega, que o Edge de teste recusa com um código; a tela mostra o texto em português
  await page.getByRole("radio", { name: "Community SNMP v2c" }).check();
  const comm = form.locator("input[type=password]");
  await expect(comm).toHaveCount(1);
  await comm.fill(COMM);
  const resp2 = page.waitForResponse((r) => r.request().method() === "POST" && r.url().includes("/credenciais"));
  await page.getByTestId("cred-enviar").click();
  const r2 = await resp2;
  expect(r2.status()).toBe(202);
  const env2 = JSON.parse(r2.request().postData() ?? "{}") as { sealed: string; kind: string };
  expect(env2.kind).toBe("snmp_community");
  await expect(comm).toHaveValue("");
  const n2 = await (await request.get(`${API_URL}/v1/edge/secret-deliveries/next`, { headers: edgeH })).json();
  expect(JSON.parse(openBlob(edge, n2.sealed, ["fibercore-seal-v1", tenant.tenant_id, tenant.edge_id, name, "snmp_community", n2.id, n2.key_id, String(n2.expires_at)].join("\n"), n2.key_id))).toEqual({ kind: "snmp_community", community: COMM });
  expect((await request.post(`${API_URL}/v1/edge/secret-deliveries/${n2.id}/result`, { headers: edgeH, data: { lease_token: n2.lease_token, outcome: "failed", code: "target_not_configured" } })).status()).toBe(204);
  await page.getByTestId("cred-atualizar").click();
  await expect(page.getByTestId("cred-codigo").first()).toContainText("habilitar credentials_file");
  await expect(page.getByTestId("cred-entregas").getByTestId("cred-estado").first()).toHaveText("Falhou");

  // o texto claro NUNCA saiu do navegador: nenhuma requisição (URL, cabeçalhos, corpo) o contém, nem em base64
  expect(sent.filter((r) => r.method === "POST" && r.url.includes("/credenciais")).length).toBeGreaterThanOrEqual(2);   // a vigilância não é vazia: os dois envios foram vistos
  for (const secret of [PW, USER, COMM]) {
    const variants = [secret, encodeURIComponent(secret), Buffer.from(secret).toString("base64"), Buffer.from(secret).toString("base64url")];
    for (const r of sent) for (const v of variants) {
      expect(r.url, `${r.method} ${r.url}`).not.toContain(v);
      expect(r.headers).not.toContain(v);
      expect(r.body ?? "").not.toContain(v);
    }
    for (const line of consoleLines) expect(line).not.toContain(secret);
  }
  // nem armazenamento local, nem a página
  const stored = await page.evaluate(() => JSON.stringify({ l: { ...localStorage }, s: { ...sessionStorage } }));
  for (const secret of [PW, USER, COMM]) { expect(stored).not.toContain(secret); await expect(page.locator("body")).not.toContainText(secret); }
  expect(await page.content()).not.toContain(PW);
  // sem violação de CSP (script inline) no console
  expect(consoleLines.filter((l) => /content security policy|refused to (execute|load)/i.test(l)), consoleLines.join("\n")).toEqual([]);
  expect(await page.locator("script:not([src]):not([nonce])").count()).toBe(0);

  // sem JavaScript: nenhum campo de segredo existe e a mensagem é de falha fechada
  const state = await context.storageState();
  const noJs = await browser.newContext({ javaScriptEnabled: false, storageState: state, baseURL: process.env.WEB_URL ?? "http://127.0.0.1:3000" });
  const p2 = await noJs.newPage();
  await p2.goto(`/rede/frota/${oltId}`);
  await expect(p2.getByTestId("frota-credenciais")).toBeVisible();
  await expect(p2.locator("input[type=password]")).toHaveCount(0);
  await expect(p2.getByTestId("cred-sem-js")).toContainText("exige JavaScript");
  await noJs.close();
});

test("credenciais: o BFF recusa origem estranha e corpo com campo extra, sem repetir o valor; a lista da API nunca devolve o blob", async ({ page, request }) => {
  test.skip(!creds(), "defina E2E_EDGE_CREDS_FILE (seed_demo.py/scripts/e2e.sh) e ligue a flag fleet_secrets");
  await login(page);
  const oltId = await registerOltAndOpenCard(page, `E2E-CSRF-${SUFFIX}`);
  const origin = new URL(page.url()).origin;
  const ok = { delivery_id: "11111111-1111-4111-8111-111111111111", kind: "ssh_login", key_id: "0123456789abcdef", expires_at: Math.floor(Date.now() / 1000) + 600, sealed: "A".repeat(150) };
  const url = `${origin}/bff/frota/olts/${oltId}/credenciais`;
  expect((await page.request.post(url, { data: ok, headers: { origin: "https://evil.example" } })).status()).toBe(403);   // CSRF: origem de outro site
  expect((await page.request.post(url, { data: ok, headers: { origin: "" } })).status()).toBe(403);                      // sem Origin
  const extra = await page.request.post(url, { data: { ...ok, password: PW }, headers: { origin } });                    // um texto claro enviado por engano
  expect(extra.status()).toBe(422);
  expect(await extra.text()).not.toContain(PW);
  expect((await page.request.post(url, { data: { ...ok, sealed: "!!!" }, headers: { origin } })).status()).toBe(422);
  const plainText = await page.request.post(url, { data: "senha=" + PW, headers: { origin, "content-type": "text/plain" } });
  expect(plainText.status()).toBe(415);
  const lst = await page.request.get(url, { headers: { "sec-fetch-site": "same-origin" } });
  expect(lst.status()).toBe(200);
  expect(await lst.text()).not.toMatch(/sealed|blob|ciphertext/i);
  expect((await page.request.get(url, { headers: { "sec-fetch-site": "cross-site" } })).status()).toBe(403);
});
