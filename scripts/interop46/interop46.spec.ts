import { expect, test, type APIRequestContext, type BrowserContext, type Page } from "@playwright/test";
import { spawn, spawnSync } from "node:child_process";
import { createECDH, createHash, randomBytes, randomUUID } from "node:crypto";
import { appendFileSync, closeSync, existsSync, mkdirSync, openSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import { API_URL, EMAIL, PASSWORD } from "../../apps/web/e2e/helpers";
import { sealOltSecret } from "../../apps/web/src/lib/oltSeal";

/**
 * Interoperação REAL do ADR-0046: navegador (Chromium/Playwright) -> web (Next, produção) -> API real (Postgres) -> Edge Go REAL (binário compilado de agents/edge, sem simulador) -> servidor SSH de TESTE
 * (scripts/interop46/sshsink) que REGISTRA toda tentativa. Nenhum valor aqui é real: senha, community e IPs são de teste e descartáveis. Este spec NUNCA imprime a senha/community/blobs.
 * Precisa da pilha de scripts/interop46/run.sh (up). As provas são seriais e guardam o estado em $INTEROP_DIR/evidence/state-run.json (dá para rodar uma prova isolada com --grep depois das anteriores).
 */
const W = process.env.INTEROP_DIR!;
const BIN = `${W}/bin/fibercore-edge`;
const PROJECT = process.env.INTEROP_COMPOSE_PROJECT ?? "fibercore-interop46";
const SINK_USER = process.env.INTEROP_SINK_USER ?? "interop-user";
const SINK_PASS = process.env.INTEROP_SINK_PASS ?? "interop-test-pass";
const EVID = `${W}/evidence`;
mkdirSync(EVID, { recursive: true });
const STATE_FILE = `${EVID}/state-run.json`;
const S: Record<string, string> = existsSync(STATE_FILE) ? JSON.parse(readFileSync(STATE_FILE, "utf8")) : {};
const SFX = (S.sfx ??= String(Date.now()).slice(-6));
const COMMUNITY = `interop-comm-${SFX}`;
const SINK_FP = readFileSync(`${W}/sink.fp`, "utf8").trim();
const WRONG_FP = "SHA256:" + createHash("sha256").update(`outra-chave-${SFX}`).digest("base64").replace(/=+$/, "");
const OTHER_FP = "SHA256:" + createHash("sha256").update(`terceira-chave-${SFX}`).digest("base64").replace(/=+$/, "");
const EMAIL_B = "admin-b@interop.example.com";
const FAKE_KEY_ID = "01234567".repeat(2); // key_id inventado (16 hex) das entregas que a API recusa antes de abri-las
const WINDOW_MS = 75_000; // >= 2 ciclos de coleta (collect_seconds=30) e >= 4 ciclos de entrega (poll_seconds=15)

// ------------------------------------------------------------------ estado e evidência
const save = () => writeFileSync(STATE_FILE, JSON.stringify(S, null, 1));
save();
function ev(prova: string, line: string) {
  console.log(`[prova ${prova}] ${line}`);
  appendFileSync(`${EVID}/prova-${prova}.txt`, line + "\n");
}
const nm = (k: string) => (S[`name_${k}`] ??= `INT46-${k}-${SFX}`);

// ------------------------------------------------------------------ sshsink (o servidor SSH de teste que registra tudo)
type SinkEv = { event: string; listener: string; ts: string; [k: string]: unknown };
const sinkAll = (): SinkEv[] => (existsSync(`${W}/sink.log`) ? readFileSync(`${W}/sink.log`, "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l) as SinkEv) : []);
const sinkMark = () => sinkAll().length;
const sinkAt = (ip: string, from = 0, port?: number) => sinkAll().slice(from).filter((e) => e.listener.startsWith(`${ip}:`) && (port === undefined || e.listener.endsWith(`:${port}`)));
const brief = (es: SinkEv[]) => es.map((e) => `${e.event}@${e.listener}${e.event === "auth_attempt" ? `(user_ok=${e.user_ok},password_ok=${e.password_ok})` : ""}${e.event === "exec" ? `(${e.cmd})` : ""}`).join(", ") || "(nenhum evento)";
/** Um envelope só com o FORMATO certo (versão 1, ponto P-256 real, nonce e tag): a API valida o formato antes do resto; quem abre é o Edge, e estes nunca chegam a um. */
function formatOnlyBlob(): string {
  const e = createECDH("prime256v1");
  e.generateKeys();
  return Buffer.concat([Buffer.from([1]), e.getPublicKey(), randomBytes(12), randomBytes(17)]).toString("base64url");
}
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

// ------------------------------------------------------------------ o Edge Go real (binário), por CLI e por processo
type Who = "A" | "B";
const cfg = (e: Who) => `${W}/edge${e}/config.json`;
const mdir = (e: Who) => `${W}/edge${e}/managed`;
function cli(e: Who, args: string[], input?: string) {
  const r = spawnSync(BIN, [args[0], "-config", cfg(e), ...args.slice(1)], { input, encoding: "utf8" });
  return { code: r.status ?? -1, out: r.stdout ?? "", err: r.stderr ?? "" };
}
const managedList = (e: Who) => cli(e, ["managed-list"]);
const localFp = (e: Who) => /fingerprint:\s*(\S+)/.exec(cli(e, ["seal-fingerprint"]).out)![1];
const pidFile = (e: Who) => `${W}/edge${e}.pid`;
function alive(pid: number) { try { process.kill(pid, 0); return true; } catch { return false; } }
async function stopEdge(e: Who) {
  const pid = existsSync(pidFile(e)) ? Number(readFileSync(pidFile(e), "utf8")) : 0;
  if (pid && alive(pid)) { process.kill(pid, "SIGTERM"); for (let i = 0; i < 50 && alive(pid); i++) await sleep(200); }
}
function startEdge(e: Who) {
  const out = openSync(`${W}/edge${e}.log`, "a");
  const c = spawn(BIN, ["-config", cfg(e)], { detached: true, stdio: ["ignore", out, out], cwd: W });
  c.unref();
  closeSync(out);
  writeFileSync(pidFile(e), String(c.pid));
}
async function restartEdge(e: Who, resetGuard: boolean) {
  await stopEdge(e);
  if (resetGuard) rmSync(`${W}/edge${e}/q/olt-guard.json`, { force: true }); // o guarda de ritmo (15 min por OLT) é do Edge; zerá-lo é só para o CONTROLE da prova (ver o doc)
  startEdge(e);
  await sleep(2000);
}
const sha = (p: string) => (existsSync(p) ? createHash("sha256").update(readFileSync(p)).digest("hex").slice(0, 16) : "(ausente)");
const mode = (p: string) => (statSync(p).mode & 0o777).toString(8);
const credFile = (e: Who, name: string) => `${mdir(e)}/creds/${name}.json`;
const edgeLogLines = (e: Who, from = 0) => (existsSync(`${W}/edge${e}.log`) ? readFileSync(`${W}/edge${e}.log`, "utf8").split("\n").filter(Boolean).slice(from) : []);

// ------------------------------------------------------------------ API (para VERIFICAR; o que a pessoa faz vai pela tela)
async function bearer(request: APIRequestContext, path: string, body: Record<string, string>) {
  const r = await request.post(`${API_URL}${path}`, { data: body });
  expect(r.status()).toBe(200);
  return { Authorization: `Bearer ${((await r.json()) as { access_token: string }).access_token}` };
}
const adminH = (request: APIRequestContext, email = EMAIL) => bearer(request, "/v1/auth/token", { email, password: PASSWORD });
const edgeH = (request: APIRequestContext, who: Who) => bearer(request, "/v1/auth/service-token", JSON.parse(readFileSync(`${W}/edge${who === "A" ? "1" : "2"}-creds.json`, "utf8")));
type OltApi = { id: string; name: string; connection: { trust_state: string | null; applied: boolean; port: number | null; host_key_sha256: string | null }; readiness: { stage: string } };
async function oltApi(request: APIRequestContext, h: Record<string, string>, id: string) {
  const r = await request.get(`${API_URL}/v1/fleet/olts/${id}`, { headers: h });
  return r.status() === 200 ? ((await r.json()) as OltApi) : null;
}
const trustOf = async (request: APIRequestContext, h: Record<string, string>, id: string) => (await oltApi(request, h, id))?.connection.trust_state ?? null;
const proxyLog = () => (existsSync(`${W}/proxy.log`) ? readFileSync(`${W}/proxy.log`, "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l) as { method: string; path: string; status: number; note: string }) : []);
const setProxy = (o: Record<string, string>) => writeFileSync(`${W}/proxy-ctrl.json`, JSON.stringify(o));

// ------------------------------------------------------------------ rede do navegador (para a prova 9) e blobs
const sealedSeen = new Set<string>();
const responses: { url: string; status: number; body: string }[] = [];
const postedPlain: string[] = [];
const NET = `${EVID}/net`; // captura da rede do navegador em disco (para a prova 9 poder rodar em outra invocação); só dentro do diretório de trabalho de TESTE
mkdirSync(NET, { recursive: true });
for (const f of existsSync(`${NET}/responses.jsonl`) ? readFileSync(`${NET}/responses.jsonl`, "utf8").split("\n").filter(Boolean) : []) responses.push(JSON.parse(f));
for (const f of existsSync(`${NET}/posts.jsonl`) ? readFileSync(`${NET}/posts.jsonl`, "utf8").split("\n").filter(Boolean) : []) { const t = JSON.parse(f) as string; postedPlain.push(t); try { const x = (JSON.parse(t) as { sealed?: string }).sealed; if (x) sealedSeen.add(x); } catch { /* */ } }
function watch(ctx: BrowserContext) {
  ctx.on("response", async (r) => {
    const u = r.url();
    if (u.includes("/_next/static") || /\.(png|svg|ico|woff2?|css|js)(\?|$)/.test(u)) return;
    try { const x = { url: u, status: r.status(), body: await r.text() }; responses.push(x); appendFileSync(`${NET}/responses.jsonl`, JSON.stringify(x) + "\n"); } catch { /* redirecionamento sem corpo */ }
  });
  ctx.on("request", (r) => {
    if (r.method() === "POST" && r.url().includes("/credenciais")) {
      const t = r.postData() ?? "";
      postedPlain.push(t);
      appendFileSync(`${NET}/posts.jsonl`, JSON.stringify(t) + "\n");
      try { const x = (JSON.parse(t) as { sealed?: string }).sealed; if (x) sealedSeen.add(x); } catch { /* corpo não JSON */ }
    }
  });
}

// ------------------------------------------------------------------ ações da tela
async function loginAs(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("E-mail").fill(email);
  await page.getByLabel("Senha").fill(PASSWORD);
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByRole("heading", { name: "Visão Geral" })).toBeVisible();
}
type Reg = { name: string; address: string; vendor?: string; protocol?: string; port?: number; hostKey?: string; snmpPort?: number; legacy?: boolean };
async function registerOlt(page: Page, o: Reg) {
  await page.goto("/rede/frota");
  const form = page.getByTestId("frota-cadastro");
  await form.getByLabel("Nome da OLT").fill(o.name);
  if (o.vendor) await form.getByLabel("Fabricante").selectOption(o.vendor);
  await form.getByLabel("Endereço de gerência (opcional)").fill(o.address);
  await form.getByLabel("Protocolo de acesso").selectOption(o.protocol ?? "ssh");
  if (o.port) await form.getByLabel("Porta de acesso").fill(String(o.port));
  if (o.hostKey) await form.getByLabel("Impressão digital do host SSH").fill(o.hostKey);
  if (o.legacy) await form.getByLabel("SSH legado").check();
  if (o.snmpPort) {
    await form.getByLabel("Versão do SNMP (opcional)").selectOption("v2c");
    await form.getByLabel("Transporte da coleta").selectOption("snmp");
    await form.getByLabel("Porta SNMP").fill(String(o.snmpPort));
  }
  await page.getByTestId("frota-cadastrar-continuar").click();
  await expect(page).toHaveURL(/\/rede\/frota\/[0-9a-f-]{36}\?ok=oltassistente/);
  return /frota\/([0-9a-f-]{36})/.exec(page.url())![1];
}
const gotoOlt = (page: Page, id: string) => page.goto(`/rede/frota/${id}`);
/** Passo da chave do Edge: a PESSOA compara a impressão digital impressa no host do Edge (CLI real) com a da tela e a redigita. */
async function confirmEdgeKey(page: Page, who: Who) {
  const fp = localFp(who);
  const card = page.getByTestId("frota-credenciais");
  await expect(async () => { await page.reload(); await expect(card.getByTestId("cred-fingerprint")).toHaveText(fp, { timeout: 3000 }); }).toPass({ timeout: 60_000 });
  if ((await card.getByTestId("cred-chave-estado").innerText()).includes("Confirmada")) return fp;
  await page.getByLabel("Digite a impressão digital mostrada no servidor do Edge").fill(fp.replaceAll("-", "").toUpperCase());
  await page.getByTestId("cred-confirmar-btn").click();
  await expect(page.getByTestId("frota-flash")).toContainText("Chave do Edge confirmada");
  return fp;
}
async function sendConnection(page: Page, address: string) {
  await page.getByTestId("conn-form").getByLabel("Endereço de gerência da OLT").fill(address);
  const resp = page.waitForResponse((r) => r.request().method() === "POST" && r.url().includes("/credenciais"));
  await page.getByTestId("conn-enviar").click();
  const r = await resp;
  expect(r.status()).toBe(202);
  const env = JSON.parse(r.request().postData() ?? "{}") as { delivery_id: string; kind: string; sealed: string };
  expect(env.kind).toBe("olt_connection");
  await expect(page.getByTestId("conn-msg")).toContainText("Conexão cifrada e enviada");
  return env;
}
async function sendSshLogin(page: Page) {
  const pw = page.getByTestId("cred-form").locator("input[type=password]");
  await pw.nth(0).fill(SINK_USER);
  await pw.nth(1).fill(SINK_PASS);
  await page.getByTestId("cred-enviar").click();
  await expect(page.getByTestId("cred-msg")).toContainText("Credencial cifrada e enviada");
}
async function sendCommunity(page: Page) {
  await page.getByRole("radio", { name: "Community SNMP v2c" }).check();
  await page.getByTestId("cred-form").locator("input[type=password]").fill(COMMUNITY);
  await page.getByTestId("cred-enviar").click();
  await expect(page.getByTestId("cred-msg")).toContainText("Credencial cifrada e enviada");
}
const connState = async (page: Page, expected: string, timeout = 110_000) => {
  await expect(async () => { await page.getByTestId("conn-atualizar").click(); await expect(page.getByTestId("conn-estado").first()).toHaveText(expected, { timeout: 4000 }); }).toPass({ timeout, intervals: [3000] });
};
const credState = async (page: Page, expected: string, timeout = 110_000) => {
  await expect(async () => { await page.getByTestId("cred-atualizar").click(); await expect(page.getByTestId("cred-estado").first()).toHaveText(expected, { timeout: 4000 }); }).toPass({ timeout, intervals: [3000] });
};
const readiness = async (page: Page) => ({ stage: await page.getByTestId("frota-prontidao-detalhe").getAttribute("data-stage"), text: (await page.getByTestId("frota-prontidao-texto").innerText()).trim() });
async function stageIs(page: Page, id: string, stage: string, timeout = 100_000) {
  await expect(async () => { await gotoOlt(page, id); expect((await readiness(page)).stage).toBe(stage); }).toPass({ timeout, intervals: [4000] });
}

test.describe.configure({ mode: "serial" });
let ctxA: BrowserContext, ctxB: BrowserContext, A: Page, B: Page;
test.beforeAll(async ({ browser }) => {
  ctxA = await browser.newContext({ locale: "pt-BR", timezoneId: "America/Manaus" });
  ctxB = await browser.newContext({ locale: "pt-BR", timezoneId: "America/Manaus" });
  watch(ctxA); watch(ctxB);
  A = await ctxA.newPage(); B = await ctxB.newPage();
  await loginAs(A, EMAIL);
});
test.afterAll(async () => { await ctxA?.close(); await ctxB?.close(); });

// ================================================================== AMBIENTE
test("ambiente: commit, Edge (binário), navegador e política local do Edge de teste", async ({ browser }) => {
  rmSync(`${EVID}/ambiente.txt`, { force: true });
  const g = (a: string[]) => (spawnSync("git", ["-C", "../..", ...a], { encoding: "utf8" }).stdout ?? "").trim();
  const edgeCfg = (e: Who) => JSON.parse(readFileSync(cfg(e), "utf8")) as { managed_olts: unknown; olt_secrets: unknown; collect_seconds: number; heartbeat_seconds: number; olts: { name: string; address: string }[] };
  const line = (t: string) => { console.log(`[ambiente] ${t}`); appendFileSync(`${EVID}/ambiente.txt`, t + "\n"); };
  line(`commit ${g(["rev-parse", "--short", "HEAD"])} (${g(["branch", "--show-current"])}); alterações não commitadas em agents/ e apps/: ${g(["status", "--porcelain", "--", "agents", "apps"]).split("\n").filter(Boolean).length}`);
  line(`binário do Edge: ${existsSync(`${W}/edge.sha`) ? readFileSync(`${W}/edge.sha`, "utf8").trim() : "(sha não registrado)"}… (sha256, go build CGO_ENABLED=0 de agents/edge/cmd/fibercore-edge); versão no log: ${(edgeLogLines("A").find((l) => l.includes("starting")) ?? "").match(/"version":"([^"]+)"/)?.[1]}`);
  line(`navegador: Chromium ${browser.version()} (Playwright)`);
  line(`Edge A (org A, via proxy de teste): ${JSON.stringify({ collect_seconds: edgeCfg("A").collect_seconds, olt_secrets: edgeCfg("A").olt_secrets && { poll_seconds: (edgeCfg("A").olt_secrets as { poll_seconds: number }).poll_seconds }, managed_olts: { ...(edgeCfg("A").managed_olts as object), state_dir: "<0700>" }, olt_estatica: edgeCfg("A").olts.map((o) => `${o.name}@${o.address}`) })}`);
  line(`Edge B (org B, direto na API): ${JSON.stringify({ managed_olts: { ...(edgeCfg("B").managed_olts as object), state_dir: "<0700>" } })}`);
  line(`state_dir do Edge A: modo ${mode(mdir("A"))}; config.json: modo ${mode(cfg("A"))}`);
});

// ================================================================== PROVA 1
test("prova 1: cadastro no navegador -> conexão selada -> o Edge real aplica -> tela 'Aguardando confirmação no Edge' + comando managed-trust -> o state chega à nuvem", async ({ request }) => {
  test.setTimeout(600_000);
  const name = nm("A");
  const mk = sinkMark();
  S.idA = await registerOlt(A, { name, address: "172.17.0.1", port: 22022, hostKey: SINK_FP });
  await expect(A.getByTestId("passo-2")).toContainText("Ainda não enviada");
  ev("1", `cadastro (passo 1) feito pela tela: OLT "${name}" id=${S.idA}, SSH porta 22022, impressão digital proposta ${SINK_FP}`);
  const fp = await confirmEdgeKey(A, "A");
  ev("1", `chave de selagem do Edge real confirmada pela pessoa: impressão digital do host do Edge (CLI seal-fingerprint) = da tela = ${fp}`);
  const env = await sendConnection(A, "172.17.0.1");
  sealedSeen.add(env.sealed);
  ev("1", `navegador enviou SÓ texto cifrado: POST /credenciais campos=${Object.keys(env).sort().join(",")}; kind=${env.kind}; sealed(${env.sealed.length} chars)`);
  await connState(A, "Aplicada");
  ev("1", `Edge real aplicou: entrega olt_connection = Aplicada (tela, passo 2)`);
  await expect(A.getByTestId("conn-confianca")).toBeVisible();
  await expect(A.getByTestId("conn-comando")).toHaveText(`fibercore-edge managed-trust ${name}`);
  await expect(A.getByTestId("conn-codigo").first()).toContainText("managed-trust");
  await A.reload();
  const r = await readiness(A);
  expect(r.stage).toBe("awaiting_trust");
  expect(r.text).toBe("Aguardando confirmação no Edge");
  ev("1", `tela: prontidão data-stage="${r.stage}", texto "${r.text}"; comando exibido: "fibercore-edge managed-trust ${name}"`);
  const h = await adminH(request);
  await expect.poll(() => trustOf(request, h, S.idA), { timeout: 60_000 }).toBe("awaiting_local_trust");
  const st = proxyLog().filter((l) => l.path === "/v1/edge/managed-olts/state");
  ev("1", `nuvem: GET /v1/fleet/olts/{id} connection.trust_state="awaiting_local_trust"; o Edge postou POST /v1/edge/managed-olts/state ${st.length}x (status: ${[...new Set(st.map((s) => s.status))].join(",") || "nenhum ainda"})`);
  const ml = managedList("A");
  expect(ml.out).toContain(name);
  ev("1", `Edge real, managed-list:\n${ml.out.trim().split("\n").map((l) => "    " + l).join("\n")}`);
  expect(sinkAt("172.17.0.1", mk)).toEqual([]);
  ev("1", `servidor SSH de teste: conexões do Edge a 172.17.0.1 durante toda a prova 1: ${brief(sinkAt("172.17.0.1", mk))}`);
  save();
});

// ================================================================== PROVA 2
test("prova 2: ANTES da confiança o servidor SSH não recebe nada; ssh_login e snmp_community são aceitos e gravados (0600) mas nunca usados", async () => {
  test.setTimeout(900_000);
  const nameA = nm("A"), nameS = nm("S");
  const mk = sinkMark();
  // ssh_login na OLT A
  await gotoOlt(A, S.idA);
  await sendSshLogin(A);
  await credState(A, "Aplicada");
  ev("2", `ssh_login da OLT A: entrega Aplicada pelo Edge (tela, passo 3). Arquivo ${credFile("A", nameA).replace(W, "$INTEROP_DIR")}: modo ${mode(credFile("A", nameA))}`);
  const content = JSON.parse(readFileSync(credFile("A", nameA), "utf8")) as Record<string, string>;
  const holds = JSON.stringify(content).includes(SINK_PASS) && JSON.stringify(content).includes(SINK_USER);
  expect(holds).toBe(true);
  expect(mode(credFile("A", nameA))).toBe("600");
  expect(mode(mdir("A") + "/creds")).toBe("700");
  ev("2", `conteúdo do arquivo: contém o login e a senha digitados na tela (conferido em memória, não impresso); diretório creds/ modo ${mode(mdir("A") + "/creds")}; campos do arquivo: ${Object.keys(content).sort().join(",")}`);
  // OLT S (SNMP): cadastro, conexão, community
  S.idS = await registerOlt(A, { name: nameS, address: "172.22.0.1", port: 22022, hostKey: SINK_FP, snmpPort: 16161 });
  await sendConnection(A, "172.22.0.1");
  await connState(A, "Aplicada");
  await sendCommunity(A);
  await credState(A, "Aplicada");
  expect(mode(credFile("A", nameS))).toBe("600");
  const comm = JSON.parse(readFileSync(credFile("A", nameS), "utf8")) as Record<string, string>;
  expect(JSON.stringify(comm)).toContain(COMMUNITY);
  ev("2", `snmp_community da OLT S (transporte SNMP, UDP 16161): entrega Aplicada; arquivo modo ${mode(credFile("A", nameS))}, contém a community digitada (não impressa); campos: ${Object.keys(comm).sort().join(",")}`);
  const h2 = await readFileSync(`${mdir("A")}/managed_olts.json`, "utf8");
  expect(h2).not.toContain(SINK_PASS);
  expect(h2).not.toContain(COMMUNITY);
  ev("2", `managed_olts.json (registro) não contém senha nem community`);
  // janela de observação: >= 2 ciclos de coleta e >= 4 de entrega, com as duas OLTs aguardando a confiança
  const t0 = Date.now();
  const logMark = edgeLogLines("A").length;
  const pollsBefore = proxyLog().filter((l) => l.path === "/v1/edge/secret-deliveries/next").length;
  await sleep(WINDOW_MS);
  const polls = proxyLog().filter((l) => l.path === "/v1/edge/secret-deliveries/next").length - pollsBefore;
  const cyc = edgeLogLines("A", logMark).filter((l) => l.includes("collector failed"));
  expect(cyc.length).toBeGreaterThanOrEqual(2);
  for (const l of cyc) { expect(l).not.toContain(nameA); expect(l).not.toContain(nameS); }
  ev("2", `ciclos de coleta do Edge na janela: ${cyc.length} linhas "collector failed" no log (uma por ciclo de 30 s; só a OLT ESTÁTICA aparece — está em espera após a falha do parser do servidor de teste —, nenhuma menção às OLTs ${nameA}/${nameS}: o coletor passou ${cyc.length}x e não as tocou)`);
  const seen = [...sinkAt("172.17.0.1", mk), ...sinkAt("172.22.0.1", mk)];
  ev("2", `janela de observação: ${Math.round((Date.now() - t0) / 1000)} s após as duas credenciais (collect_seconds=30 => >= 2 ciclos de coleta; ${polls} ciclos de entrega do Edge vistos no proxy). Estado: OLT A e OLT S em awaiting_local_trust.`);
  ev("2", `servidor SSH/UDP de teste, eventos de 172.17.0.1 (OLT A) e 172.22.0.1 (OLT S, TCP 22022 e UDP 16161) desde antes das credenciais: ${brief(seen)}`);
  expect(seen).toEqual([]);
  expect(polls).toBeGreaterThanOrEqual(3);
  const lst = managedList("A").out;
  expect(lst).toMatch(new RegExp(`${nameA}.*awaiting`));
  expect(lst).toMatch(new RegExp(`${nameS}.*awaiting`));
  save();
});

// ================================================================== PROVA 3
test("prova 3: managed-list nunca mostra credencial; managed-trust errado é recusado, certo grava; tela 'confiada'; o Edge passa a conectar e verifica a chave do host", async ({ request }) => {
  test.setTimeout(900_000);
  const nameA = nm("A"), nameS = nm("S"), nameB = nm("B");
  const h = await adminH(request);
  const ml = managedList("A");
  for (const secret of [SINK_PASS, SINK_USER, COMMUNITY]) expect(ml.out + ml.err).not.toContain(secret);
  ev("3", `managed-list (stdout) não contém senha, login nem community; colunas: NAME ADDRESS VENDOR TRANSPORT STATE POLICY PROPOSED HOST KEY FINGERPRINT`);
  // impressão digital ERRADA
  const mk0 = sinkMark();
  const wrong = cli("A", ["managed-trust", nameA], WRONG_FP + "\n");
  expect(wrong.code).not.toBe(0);
  expect(wrong.err).toContain("refused");
  expect(managedList("A").out).toMatch(new RegExp(`${nameA}.*awaiting`));
  ev("3", `managed-trust ${nameA} com impressão digital ERRADA: exit=${wrong.code}, stderr="${wrong.err.trim().split("\n").pop()}"; managed-list continua awaiting`);
  const mk = sinkMark();
  await sleep(40_000);
  expect(sinkAt("172.17.0.1", mk0)).toEqual([]);
  ev("3", `após a recusa, 40 s sem nenhuma conexão do Edge a 172.17.0.1 (servidor de teste: ${brief(sinkAt("172.17.0.1", mk0))})`);
  // impressão digital CERTA
  const right = cli("A", ["managed-trust", nameA], SINK_FP + "\n");
  expect(right.code).toBe(0);
  ev("3", `managed-trust ${nameA} com a impressão digital CERTA (a do próprio servidor da OLT de teste): exit=${right.code}; saída final: "${right.out.trim().split("\n").pop()}"`);
  expect(sha(`${mdir("A")}/trust.json`)).not.toBe("(ausente)");
  ev("3", `trust.json: modo ${mode(`${mdir("A")}/trust.json`)} (guarda o resumo SHA-256 dos campos confiados)`);
  await expect(async () => { await gotoOlt(A, S.idA); await expect(A.getByTestId("passo-2")).toContainText("confirmada no Edge", { timeout: 3000 }); }).toPass({ timeout: 100_000, intervals: [4000] });
  const r = await readiness(A);
  expect(r.stage).not.toBe("awaiting_trust");
  ev("3", `tela da OLT A: passo 2 = "${(await A.getByTestId("passo-2").innerText()).replace(/\s+/g, " ").trim().slice(0, 62)}…"; prontidão data-stage="${r.stage}" ("${r.text}"; a credencial já estava aplicada, então a etapa avança além de "confiada"); nuvem trust_state="${await trustOf(request, h, S.idA)}"`);
  expect(await trustOf(request, h, S.idA)).toBe("trusted");
  await expect(async () => {
    const es = sinkAt("172.17.0.1", mk);
    expect(es.map((e) => e.event)).toEqual(expect.arrayContaining(["tcp_accept", "auth_attempt", "session_open"]));
  }).toPass({ timeout: 120_000, intervals: [3000] });
  const aEv = sinkAt("172.17.0.1", mk);
  const auth = aEv.find((e) => e.event === "auth_attempt")!;
  expect(auth.password_ok).toBe(true);
  ev("3", `servidor de teste, OLT A depois da confiança: ${brief(aEv)} => o Edge conectou, passou a verificação da chave do host (a impressão digital pinada confere) e autenticou com a credencial entregue pela tela`);
  // SNMP
  const mkS = sinkMark();
  const ts = cli("A", ["managed-trust", nameS], SINK_FP + "\n");
  expect(ts.code).toBe(0);
  await expect(async () => { expect(sinkAt("172.22.0.1", mkS).some((e) => e.event === "udp_packet")).toBe(true); }).toPass({ timeout: 120_000, intervals: [3000] });
  ev("3", `OLT S (SNMP) confiada: managed-trust exit=${ts.code}; depois, o servidor de teste recebe pacotes UDP SNMP: ${brief(sinkAt("172.22.0.1", mkS))} (só o tamanho é registrado; a community nunca)`);
  // OLT B: impressão digital pinada ERRADA na entrega (o administrador do Edge, que não a comparou com a OLT, a confia assim mesmo)
  S.idB = await registerOlt(A, { name: nameB, address: "172.20.0.1", port: 22022, hostKey: WRONG_FP });
  await sendConnection(A, "172.20.0.1");
  await connState(A, "Aplicada");
  await sendSshLogin(A);
  await credState(A, "Aplicada");
  const mkB = sinkMark();
  const tb = cli("A", ["managed-trust", nameB], WRONG_FP + "\n");
  expect(tb.code).toBe(0);
  await expect(async () => { expect(sinkAt("172.20.0.1", mkB).some((e) => e.event === "handshake_failed")).toBe(true); }).toPass({ timeout: 120_000, intervals: [3000] });
  await sleep(20_000);
  const bEv = sinkAt("172.20.0.1", mkB);
  expect(bEv.some((e) => e.event === "auth_attempt")).toBe(false);
  ev("3", `OLT B: entrega com impressão digital pinada ERRADA (${WRONG_FP.slice(0, 20)}…, diferente da chave real do servidor), confiada localmente. Servidor de teste: ${brief(bEv)} => o Edge abriu o TCP, recebeu a chave do host, RECUSOU (chave ≠ pinada) e encerrou ANTES de qualquer autenticação: nenhuma credencial saiu do Edge`);
  const bl = edgeLogLines("A").filter((l) => l.includes(nameB)).pop() ?? "";
  ev("3", `log do Edge: ${bl.replace(/"time":"[^"]+",/, "")}`);
  save();
});

// ================================================================== PROVA 4
test("prova 4: mudar address/port/host_key na tela zera a confiança (awaiting_local_trust) e o Edge para de conectar", async ({ request }) => {
  test.setTimeout(1_800_000);
  const nameA = nm("A");
  const h = await adminH(request);
  S.addrA ??= "172.17.0.1"; S.portA ??= "22022"; S.hkA ??= SINK_FP; // o que a OLT A tem hoje na nuvem (cada variante troca para o "outro" valor)
  const ip = () => S.addrA, port = () => Number(S.portA);
  async function change(label: string, edit: () => Promise<void>, next: { addr: string; port: string; hk: string }) {
    const old = { addr: S.addrA, port: Number(S.portA) };
    await gotoOlt(A, S.idA);
    await edit();
    await A.getByTestId("frota-salvar").click();
    await expect(A.getByTestId("frota-flash")).toContainText("OLT atualizada");
    ev("4", `[${label}] editado na tela e salvo; a nuvem rebaixa a conexão: prontidão data-stage="${(await readiness(A)).stage}"`);
    await sendConnection(A, next.addr);
    await connState(A, "Aplicada");
    await expect.poll(() => trustOf(request, h, S.idA), { timeout: 60_000 }).toBe("awaiting_local_trust");
    const lst = managedList("A").out.split("\n").find((l) => l.startsWith(nameA)) ?? "";
    expect(lst).toMatch(/awaiting/);
    ev("4", `[${label}] o Edge reaplicou a conexão nova e a confiança ZEROU: nuvem trust_state="awaiting_local_trust"; managed-list: ${lst.replace(/\s+/g, " ")}`);
    await restartEdge("A", true); // guarda de ritmo (15 min por IP) zerado ANTES da janela: assim a ausência de conexão é efeito da confiança, não do ritmo
    const mk = sinkMark();
    await sleep(WINDOW_MS);
    const seenNew = sinkAt(next.addr, mk, Number(next.port)), seenOld = sinkAt(old.addr, mk, old.port);
    ev("4", `[${label}] ${WINDOW_MS / 1000} s observados (>= 2 ciclos de coleta; guarda de ritmo zerado por reinício antes da janela): servidor de teste no endpoint NOVO ${next.addr}:${next.port}: ${brief(seenNew)}; no endpoint ANTIGO ${old.addr}:${old.port}: ${brief(seenOld)} => o Edge NÃO conecta`);
    expect(seenNew).toEqual([]);
    expect(seenOld).toEqual([]);
    // CONTROLE: confiando de novo (impressão digital redigitada), no próximo ciclo o Edge conecta ao endpoint novo
    const mkC = sinkMark();
    expect(cli("A", ["managed-trust", nameA], next.hk + "\n").code).toBe(0);
    const want = next.hk === SINK_FP ? "auth_attempt" : "handshake_failed";
    await expect(async () => { expect(sinkAt(next.addr, mkC, Number(next.port)).some((e) => e.event === want)).toBe(true); }).toPass({ timeout: 120_000, intervals: [3000] });
    ev("4", `[${label}] CONTROLE: confiado de novo com a impressão digital ${next.hk === SINK_FP ? "certa" : "pinada (que NÃO é a chave real do servidor)"} => o Edge conecta ao endpoint novo: ${brief(sinkAt(next.addr, mkC, Number(next.port)))}${want === "handshake_failed" ? " (recusou a chave do host: usa a pinada NOVA)" : ""}`);
    S.addrA = next.addr; S.portA = next.port; S.hkA = next.hk; save();
  }
  void ip; void port;
  const na = S.addrA === "172.17.0.1" ? "172.18.0.1" : "172.17.0.1";
  await change("endereço", async () => { await A.locator('input[name="mgmt_address"]').fill(na); }, { addr: na, port: S.portA, hk: S.hkA });
  const np = S.portA === "22022" ? "22023" : "22022";
  await change("porta", async () => { await A.getByLabel("Porta de acesso").fill(np); }, { addr: S.addrA, port: np, hk: S.hkA });
  const nh = S.hkA === SINK_FP ? OTHER_FP : SINK_FP;
  await change("host_key", async () => { await A.getByLabel("Impressão digital do host SSH").fill(nh); }, { addr: S.addrA, port: S.portA, hk: nh });
});

// ================================================================== PROVA 5
test("prova 5: recusas da política local aparecem em português na tela", async ({ request }) => {
  test.setTimeout(900_000);
  const cases: { key: string; reg: Reg; code: string; contains: string }[] = [
    { key: "IPFORA", reg: { name: nm("IPFORA"), address: "172.19.0.1", port: 22022, hostKey: SINK_FP }, code: "address_not_allowed", contains: "fora das redes liberadas" },
    { key: "PORTA", reg: { name: nm("PORTA"), address: "172.23.0.1", port: 2299, hostKey: SINK_FP }, code: "port_not_allowed", contains: "não está liberada" },
    { key: "VENDOR", reg: { name: nm("VENDOR"), address: "172.23.0.1", port: 22022, hostKey: SINK_FP, vendor: "zte" }, code: "vendor_not_allowed", contains: "não permite este fabricante" },
    { key: "LEGACY", reg: { name: nm("LEGACY"), address: "172.23.0.1", port: 22022, hostKey: SINK_FP, legacy: true }, code: "legacy_not_allowed", contains: "não permite SSH legado" },
    { key: "CONFLITO", reg: { name: "OLT-ESTATICA-01", address: "172.23.0.1", port: 22022, hostKey: SINK_FP }, code: "name_conflict", contains: "OLT estática com este nome" },
  ];
  const mk = sinkMark();
  const ids: Record<string, string> = {};
  const before = sha(`${mdir("A")}/managed_olts.json`);
  for (const c of cases) {
    ids[c.key] = await registerOlt(A, c.reg);
    await sendConnection(A, c.reg.address);
  }
  // 5ª OLT que cabe (preenche max_olts=5: estática + A + S + B + R), e uma 6ª que estoura o máximo
  S.idR = await registerOlt(A, { name: nm("R"), address: "172.23.0.1", port: 22022, hostKey: SINK_FP });
  await sendConnection(A, "172.23.0.1");
  await connState(A, "Aplicada");
  ev("5", `OLT R (5ª no Edge: estática + A + S + B + R = max_olts 5) aceita: entrega Aplicada`);
  S.idX = await registerOlt(A, { name: nm("X"), address: "172.21.0.9", port: 22022, hostKey: SINK_FP });
  await sendConnection(A, "172.21.0.9");
  cases.push({ key: "X", reg: { name: nm("X"), address: "172.21.0.9" }, code: "too_many_olts", contains: "máximo de OLTs" });
  ids.X = S.idX;
  for (const c of cases) {
    await gotoOlt(A, ids[c.key]);
    await connState(A, "Falhou");
    const txt = await A.getByTestId("conn-codigo").first().innerText();
    expect(txt).toContain(c.contains);
    ev("5", `${c.code}: OLT "${c.reg.name}" -> estado "Falhou"; texto na tela (pt-BR): "${txt.trim()}"`);
  }
  const mid = sha(`${mdir("A")}/managed_olts.json`);
  ev("5", `nenhuma OLT recusada entrou no registro do Edge (managed-list lista só: ${managedList("A").out.split("\n").slice(1).map((l) => l.split(/\s+/)[0]).filter(Boolean).join(", ")})`);
  const refused = ["172.19.0.1", "172.23.0.1"].flatMap((ip) => sinkAt(ip, mk));
  const lst = managedList("A").out;
  for (const c of cases.filter((c) => c.key !== "X")) if (c.reg.name !== "OLT-ESTATICA-01") expect(lst).not.toContain(c.reg.name);
  expect(lst).not.toContain(nm("X"));
  ev("5", `servidor de teste: conexões do Edge a 172.19.0.1 (fora de allowed_cidrs) e 172.23.0.1 (R, aguardando confiança e recusadas): ${brief(refused)}`);
  expect(refused).toEqual([]);
  void before; void mid; void request;
  save();
});

// ================================================================== PROVA 6
test("prova 6: Telnet — a tela não pede senha, a API recusa 422 protocol_not_supported e nada é enfileirado", async ({ request }) => {
  test.setTimeout(300_000);
  const name = nm("TEL");
  const nextBefore = proxyLog().filter((l) => l.path === "/v1/edge/secret-deliveries/next" && l.status === 200).length;
  S.idTel = await registerOlt(A, { name, address: "172.23.0.7", protocol: "telnet" });
  await expect(A.getByTestId("passos-telnet")).toContainText("Telnet é só inventário");
  await expect(A.getByTestId("frota-prontidao-texto")).toHaveText("Aguardando suporte a Telnet (só cadastro)");
  await expect(A.locator("input[type=password]")).toHaveCount(0);
  await expect(A.getByTestId("conn-form")).toHaveCount(0);
  await expect(A.getByTestId("cred-envio")).toHaveCount(0);
  ev("6", `tela do cadastro Telnet: nenhum campo de senha (input[type=password]=0), sem formulário de conexão, prontidão "Aguardando suporte a Telnet (só cadastro)"`);
  const origin = new URL(A.url()).origin;
  const h = await adminH(request);
  const olt = await oltApi(request, h, S.idTel);
  expect(olt).not.toBeNull();
  for (const kind of ["olt_connection", "ssh_login", "snmp_community"]) {
    const body = { delivery_id: randomUUID(), kind, key_id: FAKE_KEY_ID, expires_at: Math.floor(Date.now() / 1000) + 600, sealed: formatOnlyBlob() };
    const r = await A.request.post(`${origin}/bff/frota/olts/${S.idTel}/credenciais`, { data: body, headers: { origin } });
    ev("6", `POST /bff/frota/olts/{telnet}/credenciais kind=${kind}: HTTP ${r.status()} detail=${JSON.stringify(((await r.json().catch(() => ({}))) as { detail?: string }).detail)}`);
    expect([422, 400]).toContain(r.status());
  }
  const list = await request.get(`${API_URL}/v1/fleet/olts/${S.idTel}/secret-deliveries`, { headers: h });
  const items = ((await list.json()) as { items: unknown[] }).items;
  expect(items).toHaveLength(0);
  await sleep(20_000);
  const nextAfter = proxyLog().filter((l) => l.path === "/v1/edge/secret-deliveries/next" && l.status === 200).length;
  ev("6", `GET /v1/fleet/olts/{telnet}/secret-deliveries: ${items.length} item(ns) (nada enfileirado); entregas 200 vistas pelo Edge A desde o início da prova: ${nextAfter - nextBefore}`);
  expect(nextAfter - nextBefore).toBe(0);
  save();
});

// ================================================================== PROVA 7
test("prova 7: entrega forjada e replay não regravam nem duplicam; remove / removed zera na nuvem", async ({ request }) => {
  test.setTimeout(1_200_000);
  const nameR = nm("R");
  const h = await adminH(request);
  const reg = () => sha(`${mdir("A")}/managed_olts.json`);
  const row = () => managedList("A").out.split("\n").filter((l) => l.startsWith(nameR));
  await gotoOlt(A, S.idR);
  if (row().length === 0) { await sendConnection(A, "172.23.0.1"); await connState(A, "Aplicada"); } // (repetição da prova: a OLT R já foi removida antes)
  expect(row()).toHaveLength(1);
  const base = reg();
  ev("7", `base: OLT R no registro do Edge (${row()[0].replace(/\s+/g, " ")}); sha256(managed_olts.json)[:16]=${base}`);
  // --- forjadas (o proxy de teste entre o Edge e a API adultera o que o Edge recebe)
  for (const m of ["tamper_sealed", "tamper_sig", "tamper_olt"]) {
    setProxy({ mode: m });
    await gotoOlt(A, S.idR);
    await sendConnection(A, "172.23.0.1");
    await connState(A, "Falhou");
    const code = (await A.getByTestId("conn-codigo").first().innerText()).trim();
    ev("7", `forjada (${m}): Edge recusou; tela: "Falhou" — "${code}"; sha256(registro)=${reg()} ${reg() === base ? "(inalterado)" : "(MUDOU!)"}`);
    expect(reg()).toBe(base);
  }
  setProxy({ mode: "pass" });
  // --- uma entrega legítima de verdade (porta 22023): aplica e muda o registro
  await gotoOlt(A, S.idR);
  const curPort = (await oltApi(request, h, S.idR))!.connection.port;
  const newPort = curPort === 22023 ? "22022" : "22023";
  await A.getByLabel("Porta de acesso").fill(newPort);
  await A.getByTestId("frota-salvar").click();
  await expect(A.getByTestId("frota-flash")).toContainText("OLT atualizada");
  const first = await sendConnection(A, "172.23.0.1");
  await connState(A, "Aplicada");
  const applied = reg();
  expect(applied).not.toBe(base);
  const capDir = `${W}/captured`;
  const capFiles = readdirSyncSafe(capDir);
  ev("7", `entrega legítima (porta ${curPort} -> ${newPort}) Aplicada; registro mudou para ${applied}; ${capFiles.length} entregas capturadas pelo proxy`);
  // --- replay no Edge: o proxy reentrega a PRIMEIRA entrega capturada de R (delivery_id antigo, já aplicado ou substituído)
  const sorted = capFiles.map((f) => ({ f, t: statSync(`${capDir}/${f}`).mtimeMs, d: JSON.parse(readFileSync(`${capDir}/${f}`, "utf8")) as { id: string; olt_name: string; kind: string } }))
    .filter((x) => x.d.olt_name === nameR && x.d.kind === "olt_connection").sort((a, b) => a.t - b.t);
  const targets = sorted.length > 1 ? [sorted[0], sorted[sorted.length - 1]] : [sorted[0]]; // a entrega MAIS ANTIGA de R (valor antigo: restaurá-lo seria o dano) e a que acabou de ser aplicada
  for (const [i, t] of targets.entries()) {
    const replayFile = `${capDir}/${t.f}`, replayId = t.d.id;
    const replaysBefore = proxyLog().filter((l) => l.note === "replayed").length;
    setProxy({ mode: "replay", file: replayFile });
    await sleep(35_000);
    const replays = proxyLog().filter((l) => l.note === "replayed").length - replaysBefore;
    setProxy({ mode: "pass" });
    const results = proxyLog().filter((l) => l.path.includes(`/v1/edge/secret-deliveries/${replayId}/result`)).map((l) => l.status);
    ev("7", `replay no Edge (${i === 0 ? "entrega MAIS ANTIGA de R" : "entrega que acabou de ser aplicada"}, delivery_id ${replayId.slice(0, 8)}…): servida ${replays}x pelo proxy no lugar da fila; resultados que o Edge enviou à API por ela (status, no total): [${results.join(",")}] (o Edge reconhece o delivery_id já aplicado ou substituído, responde sem regravar; a API trata resultado repetido como no-op)`);
    expect(replays).toBeGreaterThanOrEqual(2);
    expect(reg()).toBe(applied);
    expect(row()).toHaveLength(1);
    ev("7", `   depois do replay: sha256(registro)=${reg()} (igual a ${applied}); managed-list lista "${nameR}" ${row().length}x (sem duplicata, sem voltar ao valor antigo): ${row()[0].replace(/\s+/g, " ")}`);
  }
  // --- replay na API: o mesmo delivery_id, pelo navegador
  const origin = new URL(A.url()).origin;
  const before = ((await (await request.get(`${API_URL}/v1/fleet/olts/${S.idR}/secret-deliveries`, { headers: h })).json()) as { items: unknown[] }).items.length;
  const dup = await A.request.post(`${origin}/bff/frota/olts/${S.idR}/credenciais`, { data: JSON.parse(postedPlain.filter((p) => p.includes(first.delivery_id)).pop()!), headers: { origin } });
  const after = ((await (await request.get(`${API_URL}/v1/fleet/olts/${S.idR}/secret-deliveries`, { headers: h })).json()) as { items: unknown[] }).items.length;
  ev("7", `replay na API (mesmo delivery_id reenviado pelo navegador): HTTP ${dup.status()} detail=${JSON.stringify(((await dup.json().catch(() => ({}))) as { detail?: string }).detail)}; entregas da OLT antes/depois: ${before}/${after}`);
  expect(dup.status()).toBe(409);
  expect(after).toBe(before);
  // --- uma credencial para R, para provar que o remove também apaga o arquivo de credenciais
  await gotoOlt(A, S.idR);
  await sendSshLogin(A);
  await credState(A, "Aplicada");
  expect(existsSync(credFile("A", nameR))).toBe(true);
  ev("7", `antes do remove: R tem arquivo de credenciais (modo ${mode(credFile("A", nameR))})`);
  // --- remove (a tela não tem botão: o selador de produção apps/web/src/lib/oltSeal.ts, pela sessão do navegador e pelo BFF)
  const edgeId = ((await (await request.get(`${API_URL}/v1/edges`, { headers: h })).json()) as { id: string }[])[0].id;
  const key = (await (await A.request.get(`${origin}/bff/frota/edges/${edgeId}/chave`)).json()) as { tenant_id: string; edge_id: string; key_id: string; public_key: string; server_time: number };
  const deliveryId = randomUUID();
  const expires = key.server_time + 1800;
  const sealed = await sealOltSecret({ tenantId: key.tenant_id, edgeId: key.edge_id, oltName: nameR, deliveryId, keyId: key.key_id, expiresAtUnix: expires, edgePublicKey: key.public_key, plain: { kind: "olt_connection", action: "remove", cloud_id: S.idR } });
  sealedSeen.add(sealed.sealed);
  const rm = await A.request.post(`${origin}/bff/frota/olts/${S.idR}/credenciais`, { data: { delivery_id: deliveryId, kind: "olt_connection", key_id: key.key_id, expires_at: expires, sealed: sealed.sealed }, headers: { origin } });
  expect(rm.status()).toBe(202);
  await expect.poll(() => row().length, { timeout: 100_000, intervals: [3000] }).toBe(0);
  ev("7", `remove (selado com o selador de produção; sem botão na tela): Edge aplicou; managed-list não lista mais "${nameR}"; arquivo de credenciais: ${existsSync(credFile("A", nameR)) ? "AINDA EXISTE" : "apagado"}`);
  expect(existsSync(credFile("A", nameR))).toBe(false);
  await expect.poll(() => trustOf(request, h, S.idR), { timeout: 100_000, intervals: [3000] }).toBe("none");
  const o = await oltApi(request, h, S.idR);
  const st = proxyLog().filter((l) => l.path === "/v1/edge/managed-olts/state").length;
  ev("7", `nuvem depois de "removed": connection.trust_state="${o!.connection.trust_state}", prontidão "${o!.readiness.stage}" (o Edge postou o estado ${st}x no total)`);
  await stageIs(A, S.idR, "registered");
  ev("7", `tela da OLT R: prontidão volta a "${(await readiness(A)).text}" (data-stage=registered)`);
  save();
});

// ================================================================== PROVA 8
test("prova 8: isolamento — outra organização com outro Edge real não vê a OLT, a entrega nem o estado da primeira", async ({ request }) => {
  test.setTimeout(1_200_000);
  const nameO = nm("ORGB");
  await loginAs(B, EMAIL_B);
  if (!S.idO) { // (a repetição da prova pula o ciclo completo da org B, que já foi feito)
  S.idO = await registerOlt(B, { name: nameO, address: "172.19.0.1", port: 22022, hostKey: SINK_FP });
  await confirmEdgeKey(B, "B");
  ev("8", `org B: Edge B REAL (outro processo, outro config, outra chave de selagem ${localFp("B")}) com a chave confirmada pela pessoa da org B; OLT "${nameO}" cadastrada (172.19.0.1, rede que o Edge A NÃO libera, o Edge B sim)`);
  await sendConnection(B, "172.19.0.1");
  await connState(B, "Aplicada");
  await sendSshLogin(B);
  await credState(B, "Aplicada");
  const mkO = sinkMark();
  expect(cli("B", ["managed-trust", nameO], SINK_FP + "\n").code).toBe(0);
  await expect(async () => { expect(sinkAt("172.19.0.1", mkO).some((e) => e.event === "auth_attempt")).toBe(true); }).toPass({ timeout: 120_000, intervals: [3000] });
  ev("8", `org B fecha o ciclo completo com o Edge B: confiada, o servidor de teste vê ${brief(sinkAt("172.19.0.1", mkO))}`);
  save();
  }
  // registros locais: cada Edge só tem as suas OLTs
  const la = managedList("A").out, lb = managedList("B").out;
  expect(lb).toContain(nameO);
  expect(lb).not.toContain(nm("A"));
  expect(la).not.toContain(nameO);
  ev("8", `Edge A (managed-list) não lista "${nameO}"; Edge B (managed-list) lista só: ${lb.split("\n").slice(1).map((l) => l.split(/\s+/)[0]).filter(Boolean).join(", ")} (nenhuma OLT da org A)`);
  // API: a pessoa da org B e o Edge B não alcançam nada da org A
  const hA = await adminH(request, EMAIL), hB = await adminH(request, EMAIL_B);
  const eB = await edgeH(request, "B"), eA = await edgeH(request, "A");
  const edgeAId = ((await (await request.get(`${API_URL}/v1/edges`, { headers: hA })).json()) as { id: string }[])[0].id;
  const codes: string[] = [];
  const probe = async (label: string, p: Promise<{ status(): number }>, want: number[]) => { const s = (await p).status(); codes.push(`${label}=${s}`); expect(want, label).toContain(s); };
  await probe("B lê OLT da org A", request.get(`${API_URL}/v1/fleet/olts/${S.idA}`, { headers: hB }), [404]);
  await probe("B lista entregas da OLT da org A", request.get(`${API_URL}/v1/fleet/olts/${S.idA}/secret-deliveries`, { headers: hB }), [404]);
  await probe("B lê a chave do Edge da org A", request.get(`${API_URL}/v1/fleet/edges/${edgeAId}/seal-key`, { headers: hB }), [404]);
  await probe("B entrega algo à OLT da org A", request.post(`${API_URL}/v1/fleet/olts/${S.idA}/secret-deliveries`, { headers: hB, data: { delivery_id: randomUUID(), kind: "olt_connection", key_id: FAKE_KEY_ID, expires_at: Math.floor(Date.now() / 1000) + 600, sealed: formatOnlyBlob() } }), [404]);
  const listB = (await (await request.get(`${API_URL}/v1/fleet/olts`, { headers: hB })).json()) as { items?: { id: string }[] } | { id: string }[];
  const idsB = (Array.isArray(listB) ? listB : listB.items ?? []).map((o) => o.id);
  const listA = (await (await request.get(`${API_URL}/v1/fleet/olts`, { headers: hA })).json()) as { items?: { id: string }[] } | { id: string }[];
  const idsA = (Array.isArray(listA) ? listA : listA.items ?? []).map((o) => o.id);
  expect(idsB).toContain(S.idO);
  expect(idsB).not.toContain(S.idA);
  expect(idsA).not.toContain(S.idO);
  ev("8", `API como pessoa/Edge da org B: ${codes.join("; ")}; lista de OLTs da org B (${idsB.length}) não contém nenhuma da org A (${idsA.length} OLTs) e vice-versa`);
  // estado: o Edge B tenta reportar por uma OLT da org A (e o A por uma da B): ignorado, sem mudar nada
  const before = await trustOf(request, hA, S.idA);
  const r1 = await request.post(`${API_URL}/v1/edge/managed-olts/state`, { headers: eB, data: { items: [{ cloud_id: S.idA, state: "removed" }, { cloud_id: S.idS, state: "trusted" }] } });
  const j1 = await r1.json();
  const afterA = await trustOf(request, hA, S.idA);
  const r2 = await request.post(`${API_URL}/v1/edge/managed-olts/state`, { headers: eA, data: { items: [{ cloud_id: S.idO, state: "removed" }] } });
  const j2 = await r2.json();
  const afterO = await trustOf(request, hB, S.idO);
  expect(j1).toEqual({ updated: 0, ignored: 2 });
  expect(j2).toEqual({ updated: 0, ignored: 1 });
  expect(afterA).toBe(before);
  expect(afterO).toBe("trusted");
  ev("8", `estado: Edge B reportando "removed"/"trusted" por OLTs da org A => ${JSON.stringify(j1)}; trust_state da OLT A antes/depois: ${before}/${afterA}. Edge A reportando "removed" pela OLT da org B => ${JSON.stringify(j2)}; trust_state da OLT B: ${afterO}`);
  // entrega: com o Edge A PARADO, uma entrega da org A fica PENDING e o Edge B (token válido) não a vê nem consegue dar resultado por ela
  await stopEdge("A");
  await gotoOlt(A, S.idS);
  const env = await sendConnection(A, "172.22.0.1");
  void env;
  const nB = await request.get(`${API_URL}/v1/edge/secret-deliveries/next`, { headers: eB });
  ev("8", `com o Edge A parado, uma entrega da org A fica PENDING; Edge B (token válido) consulta GET /v1/edge/secret-deliveries/next => HTTP ${nB.status()} (204 = nada para ele)`);
  expect(nB.status()).toBe(204);
  const dl = ((await (await request.get(`${API_URL}/v1/fleet/olts/${S.idS}/secret-deliveries`, { headers: hA })).json()) as { items: { id: string; status: string }[] }).items;
  const pend = dl.find((d) => d.status === "PENDING")!;
  expect(pend).toBeTruthy();
  const forged = await request.post(`${API_URL}/v1/edge/secret-deliveries/${pend.id}/result`, { headers: eB, data: { lease_token: randomUUID(), outcome: "applied" } });
  ev("8", `Edge B tenta enviar resultado "applied" para a entrega da org A: HTTP ${forged.status()}; a entrega segue ${((await (await request.get(`${API_URL}/v1/fleet/olts/${S.idS}/secret-deliveries`, { headers: hA })).json()) as { items: { id: string; status: string }[] }).items.find((d) => d.id === pend.id)?.status}`);
  expect([404, 409, 422]).toContain(forged.status());
  startEdge("A");
  await connState(A, "Aplicada");
  ev("8", `Edge A volta e aplica a entrega da org A normalmente (estado "Aplicada")`);
  save();
});

// ================================================================== PROVA 9
test("prova 9: nenhum segredo (senha, community, blob) em logs do Edge, da API, do web nem em respostas", async () => {
  test.setTimeout(300_000);
  expect(sealedSeen.size, "captura de rede vazia: rode as provas 1-8 antes (ou o spec inteiro)").toBeGreaterThanOrEqual(8);
  expect(responses.length).toBeGreaterThan(20);
  const secrets: [string, string][] = [["senha", SINK_PASS], ["community", COMMUNITY]];
  const compose = spawnSync("docker", ["compose", "-p", PROJECT, "logs", "--no-color", "--no-log-prefix"], { encoding: "utf8", maxBuffer: 256 * 1024 * 1024 });
  const files: [string, string][] = [
    ["log do Edge A", readFileSync(`${W}/edgeA.log`, "utf8")], ["log do Edge B", readFileSync(`${W}/edgeB.log`, "utf8")],
    ["log do web (next)", readFileSync(`${W}/web.log`, "utf8")], ["logs da API/Postgres/NATS/workers (docker compose logs)", compose.stdout + compose.stderr],
    ["log do proxy de teste", readFileSync(`${W}/proxy.log`, "utf8")], ["log do servidor SSH de teste", readFileSync(`${W}/sink.log`, "utf8")],
  ];
  // controle positivo: o mesmo método de busca ACHA a senha onde ela deve estar (o arquivo de credenciais do Edge, 0600) e o login no log do servidor de teste (que registra o usuário esperado, nunca a senha)
  const where = readFileSync(credFile("A", nm("A")), "utf8");
  expect(where.split(SINK_PASS).length - 1).toBe(1);
  ev("9", `controle positivo: a busca acha a senha de teste exatamente 1x no arquivo de credenciais do Edge A (onde DEVE estar), logo as 0 ocorrências abaixo não vêm de uma busca cega`);
  // o usuário do login também não deve vazar fora do que o Edge guarda
  const user = ["login", SINK_USER] as [string, string];
  let report = "";
  for (const [label, text] of files) {
    for (const [k, v] of [...secrets, user]) {
      const n = text.split(v).length - 1;
      report += `${label}: ${k} ocorrências=${n}; `;
      if (k !== "login" || label !== "log do servidor SSH de teste") expect(n, `${label} contém ${k}`).toBe(0);
    }
    let blobs = 0;
    for (const b of sealedSeen) if (text.includes(b)) blobs++;
    report += `blobs selados=${blobs}\n`;
    expect(blobs, `${label} contém blob selado`).toBe(0);
  }
  ev("9", `${files.length} fontes de log varridas (${files.map((f) => `${f[0]}: ${f[1].length} bytes`).join("; ")}) contra a senha, a community, o login de teste e ${sealedSeen.size} blobs selados vistos na rede do navegador:`);
  for (const l of report.trim().split("\n")) ev("9", "    " + l);
  // respostas ao navegador (API via BFF e páginas)
  let hits = 0;
  for (const r of responses) {
    for (const [, v] of [...secrets, user]) if (r.body.includes(v)) hits++;
    for (const b of sealedSeen) if (r.body.includes(b)) hits++;
  }
  ev("9", `${responses.length} respostas HTTP vistas pelo navegador (páginas, BFF, API): ocorrências de senha/community/login/blob: ${hits}`);
  expect(hits).toBe(0);
  const fullIps = responses.flatMap((r) => r.body.match(/\b172\.(?:1[7-9]|2[0-3])\.\d{1,3}\.\d{1,3}\b/g) ?? []).length;
  ev("9", `endereço de gerência inteiro (IP completo das OLTs de teste) em respostas ao navegador: ${fullIps} (a nuvem só devolve a máscara 172.x.•.•)`);
  expect(fullIps).toBe(0);
  // saída do navegador: os POST /credenciais só carregam texto cifrado
  const plainHits = postedPlain.filter((p) => [SINK_PASS, COMMUNITY, SINK_USER, "172.17.0.1", "172.22.0.1", "172.18.0.1", "172.19.0.1"].some((s) => p.includes(s))).length;
  ev("9", `${postedPlain.length} POST /credenciais do navegador: corpos com senha, community, login ou IP em claro: ${plainHits}`);
  expect(plainHits).toBe(0);
  // banco: depois de terminada, a entrega não guarda mais o texto cifrado (blob apagado); a nuvem só guardou cifrado enquanto esperava
  const q = spawnSync("docker", ["compose", "-p", PROJECT, "exec", "-T", "postgres", "psql", "-U", "fibercore", "-d", "fibercore", "-At", "-F", "|", "-c", "SELECT status, kind, count(*), count(sealed) FROM olt_secret_deliveries GROUP BY status, kind ORDER BY 1, 2"], { encoding: "utf8" });
  ev("9", `banco (status|kind|entregas|com blob): ${q.stdout.trim().split("\n").join("; ")}`);
  expect(q.status).toBe(0);
  for (const l of q.stdout.trim().split("\n")) { const [st, , , withBlob] = l.split("|"); if (st !== "PENDING" && st !== "DISPATCHED") expect(Number(withBlob), l).toBe(0); }
  // arquivos do Edge: o armazém de aplicadas e o registro não guardam segredo
  for (const e of ["A", "B"] as Who[]) {
    for (const f of [`${W}/edge${e}/olt-secrets-applied.json`, `${mdir(e)}/managed_olts.json`, `${mdir(e)}/trust.json`]) {
      if (!existsSync(f)) continue;
      const t = readFileSync(f, "utf8");
      for (const [, v] of [...secrets, user]) expect(t.includes(v), f).toBe(false);
    }
  }
  ev("9", `armazém de entregas aplicadas, registro e trust.json dos dois Edges: sem senha, community nem login`);
});

function readdirSyncSafe(d: string): string[] { try { return readdirSync(d); } catch { return []; } }
