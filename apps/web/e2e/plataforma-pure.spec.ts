import { expect, test } from "@playwright/test";
import { ACTION_LABEL, closureCommands, CLOSURE_STATE, graceOver, rowsDeleted, shellQuote, cursorQuery, decodeFlash, encodeFlash, FEATURE_FORMAT, featureChoices, healthText, historyText, inviteLabel, limitsDiff, limitsPayload, invitePath, orgError, ORG_ERRORS, ORG_FLASH, stepUpError } from "../src/lib/platform";

// Organizações da plataforma (ADR-0046 D1): mapa de erros, cookie de aviso do link do convite e textos. Funções puras: sem navegador nem API.
const TOKEN = "A".repeat(43);

test("cada erro da API vira um código curto e todo código tem texto em português", () => {
  expect(orgError(403, { detail: "mfa_recent_required" })).toBe("mfa");
  expect(orgError(403, { detail: "forbidden" })).toBe("permissao");
  expect(orgError(409, { detail: "organization_name_taken" })).toBe("duplicada");
  expect(orgError(409, { detail: "outra coisa" })).toBe("falha");
  expect(orgError(429, { detail: "organization_rate_limited" })).toBe("limite");
  expect(orgError(422, { detail: "organization_name_invalid" })).toBe("nome");
  expect(orgError(422, { detail: "organization_email_invalid" })).toBe("email");
  expect(orgError(422, { detail: "organization_admin_name_invalid" })).toBe("admin");
  expect(orgError(422, { detail: [{ type: "value_error", loc: ["body", "admin_email"], msg: "x" }] })).toBe("email");
  expect(orgError(422, { detail: [{ type: "string_too_short", loc: ["body", "name"], msg: "x" }] })).toBe("nome");
  expect(orgError(422, { detail: [{ type: "x", loc: ["body", "zzz"], msg: "x" }] })).toBe("invalido");
  expect(orgError(500, null)).toBe("falha");
  expect(stepUpError(401)).toBe("codigo");
  expect(stepUpError(409)).toBe("semmfa");
  expect(stepUpError(429)).toBe("tentativas");
  expect(stepUpError(502)).toBe("falha");
  for (const code of ["duplicada", "limite", "mfa", "nome", "email", "admin", "invalido", "permissao", "codigo", "semmfa", "tentativas", "falha"]) expect(ORG_ERRORS[code]).toMatch(/\S/);
  expect(Object.values(ORG_ERRORS).join(" ")).not.toMatch(/organization_|mfa_recent|forbidden/);   // nenhum código técnico da API chega à tela
});

test("o aviso do link do convite vai e volta pelo cookie sem perder nada e recusa o que não tem o formato", () => {
  const raw = encodeFlash({ tenant_id: "t", name: "Provedor Ç", invite: { id: "i", state: "pending", role: "isp_admin", email: "ana@exemplo.com", expires_at: "2026-11-15T10:00:00+00:00", token: TOKEN } });
  expect(raw).toMatch(/^[A-Za-z0-9_-]+$/);   // seguro para valor de cookie
  expect(decodeFlash(raw)).toEqual({ name: "Provedor Ç", email: "ana@exemplo.com", state: "pending", expires: "2026-11-15T10:00:00+00:00", token: TOKEN });
  expect(decodeFlash(undefined)).toBeNull();
  expect(decodeFlash("isso-nao-e-base64-de-json")).toBeNull();
  const bad = Buffer.from(JSON.stringify({ n: "x", e: "y", s: "pending", x: "z", t: "curto" })).toString("base64url");
  expect(decodeFlash(bad)).toBeNull();   // token fora do formato: nada é mostrado
  const inj = Buffer.from(JSON.stringify({ n: "x", e: "y", s: "pending", x: "z", t: `${TOKEN}"><script>` })).toString("base64url");
  expect(decodeFlash(inj)).toBeNull();
});

test("o link do convite é só o caminho: nenhum host entra nele", () => {
  expect(invitePath(TOKEN)).toBe(`/convite/${TOKEN}`);
});

test("o estado do convite tem rótulo para cada valor e um traço para nenhum", () => {
  expect(inviteLabel("pending")).toContain("Pendente");
  expect(inviteLabel("accepted")).toBe("Aceito");
  expect(inviteLabel("expired")).toContain("Expirou");
  expect(inviteLabel("revoked")).toBe("Revogado");
  expect(inviteLabel(null)).toBe("—");
});

test("o cursor da lista só passa instante e id no formato certo", () => {
  const id = "0b9d6e0c-3b5a-4c0e-8d57-1f3a5f6a7b8c";
  expect(cursorQuery(`2026-11-12T10:00:00.123456+00:00~${id}`)).toBe(`before_at=2026-11-12T10%3A00%3A00.123456%2B00%3A00&before_id=${id}`);
  expect(cursorQuery(`2026-11-12T10:00:00Z~${id}`)).toContain("before_at=2026-11-12T10%3A00%3A00Z");
  for (const bad of ["", "lixo", `2026-11-12~${id}`, `2026-11-12T10:00:00Z~nao-e-uuid`, `2026-11-12T10:00:00Z&x=1~${id}`, `2026-11-12T10:00:00Z~${id}&y=2`]) expect(cursorQuery(bad)).toBe("");
});

test("erros novos do ciclo de vida viram código curto e todo código tem texto em português", () => {
  expect(orgError(404, { detail: "organization_not_found" })).toBe("naoencontrada");
  expect(orgError(422, { detail: "organization_reason_invalid" })).toBe("motivo");
  expect(orgError(422, { detail: [{ type: "string_too_short", loc: ["body", "reason"], msg: "x" }] })).toBe("motivo");
  expect(orgError(422, { detail: "unknown_feature" })).toBe("flag");
  expect(orgError(422, { detail: "feature_state_invalid" })).toBe("flag");
  expect(orgError(422, { detail: "feature_precondition" })).toBe("precondicao");
  expect(orgError(403, { detail: "owner_only_feature" })).toBe("somentedono");
  expect(orgError(403, { detail: "forbidden" })).toBe("permissao");
  for (const code of ["naoencontrada", "motivo", "flag", "somentedono", "precondicao"]) expect(ORG_ERRORS[code]).toMatch(/\S/);
  for (const code of ["suspensa", "reativada", "renomeada", "flagok", "semmudanca"]) expect(ORG_FLASH[code]).toMatch(/\S/);
  expect(Object.values(ORG_ERRORS).join(" ") + Object.values(ORG_FLASH).join(" ")).not.toMatch(/organization_|owner_only|feature_|unknown_/);
});

test("recursos que escrevem na rede só oferecem desligar; os demais oferecem tudo", () => {
  expect(featureChoices({ owner_only: true })).toEqual(["off", "default"]);
  expect(featureChoices({ owner_only: false })).toEqual(["on", "off", "default"]);
  expect(FEATURE_FORMAT.test("onu_discovery")).toBe(true);
  for (const bad of ["", "A", "x", "1abc", "a-b", "a b", "a/../b", `a${"b".repeat(64)}`]) expect(FEATURE_FORMAT.test(bad)).toBe(false);
});

test("saúde e histórico viram texto curto, só com chaves conhecidas", () => {
  expect(healthText({ edges_online: 1, edges_total: 2, olts_stale: 0 })).toBe("1/2 Edges online · 0 OLTs sem coleta");
  expect(healthText({ edges_online: 1, edges_total: 1, olts_stale: 1 })).toBe("1/1 Edge online · 1 OLT sem coleta");
  expect(historyText({ at: "x", action: "platform.organization.suspended", actor: "Ana", detail: { from: "active", to: "suspended", reason: "Contrato encerrado" } })).toBe("ativa → suspensa · motivo: Contrato encerrado");
  expect(historyText({ at: "x", action: "platform.feature.set", actor: null, detail: { feature: "onu_discovery", from: "default", to: "on", reason: "Piloto" } })).toBe("onu_discovery: padrão → ligado · motivo: Piloto");
  expect(historyText({ at: "x", action: "platform.organization.created", actor: "Ana", detail: { name: "Provedor X" } })).toBe("Provedor X");
  expect(ACTION_LABEL["platform.organization.suspended"]).toBe("Suspensa");
});

test("limites técnicos: formulário vira corpo da API, faixas e de→para legível (ADR-0047 D3)", () => {
  const form = (o: Record<string, string>) => (n: string) => o[n] ?? "";
  expect(limitsPayload(form({ max_olts: "7" }))).toEqual({ limits: { max_olts: 7 } });
  expect(limitsPayload(form({ max_olts: " 12 ", default_max_edges: "1", ingest_burst: "0" }))).toEqual({ erro: "limites" });   // burst mínimo é 1
  expect(limitsPayload(form({ max_olts: "12", default_max_edges: "1" }))).toEqual({ limits: { max_olts: 12, max_edges: null } });
  expect(limitsPayload(form({ default_max_members: "1", max_members: "5" }))).toEqual({ limits: { max_members: null } });   // "Padrão" vence o número
  expect(limitsPayload(form({}))).toEqual({ erro: "semlimite" });
  for (const bad of ["-1", "1.5", "abc", "1e3", "100001", "99999999"]) expect(limitsPayload(form({ max_olts: bad })), bad).toEqual({ erro: "limites" });
  expect(limitsPayload(form({ max_olts: "0" }))).toEqual({ limits: { max_olts: 0 } });   // zero é válido: nenhuma OLT nova
  expect(limitsPayload(form({ ingest_per_minute: "60001" }))).toEqual({ erro: "limites" });
  expect(orgError(422, { detail: "limits_invalid" })).toBe("limites");
  expect(ORG_ERRORS.limites).toBeTruthy(); expect(ORG_ERRORS.semlimite).toBeTruthy(); expect(ORG_FLASH.limitesok).toBe("Limites atualizados.");
  expect(ACTION_LABEL["platform.limits.set"]).toBe("Limites alterados");
  const nulls = { max_edges: null, max_olts: null, max_members: null, ingest_per_minute: null, ingest_burst: null };
  expect(limitsDiff(nulls, { ...nulls, max_olts: 7, ingest_burst: 5 })).toBe("OLTs: padrão → 7; rajada: padrão → 5");
  expect(limitsDiff({ ...nulls, max_olts: 7 }, nulls)).toBe("OLTs: 7 → padrão");
  expect(limitsDiff(nulls, nulls)).toBe("");
  expect(limitsDiff("active", "suspended")).toBe("");
  expect(historyText({ at: "x", action: "platform.limits.set", actor: "Ana", detail: { from: nulls, to: { ...nulls, max_members: 5 }, reason: "Piloto pequeno" } })).toBe("Membros: padrão → 5 · motivo: Piloto pequeno");
});

test("cadastro de OLT: limite atingido mostra X de Y só com inteiros; senão a frase geral", async () => {
  const { oltLimitText, fleetErrorText, FLEET_FLASH } = await import("../src/lib/fleet");
  expect(oltLimitText("3", "3")).toBe("Limite de OLTs desta organização atingido (3 de 3). Peça ao operador da plataforma para ajustar.");
  expect(oltLimitText(0, 0)).toContain("(0 de 0)");
  for (const bad of [["", ""], ["x", "3"], ["-1", "3"], ["1.5", "3"], ["99999999", "3"], [undefined, undefined]]) expect(oltLimitText(bad[0], bad[1])).toBe(FLEET_FLASH.limiteolts);
  expect(fleetErrorText({ detail: "limiteolts", atual: "2", max: "2" })).toContain("(2 de 2)");
  expect(fleetErrorText({ detail: "nome" })).toBe(FLEET_FLASH.nome);
  expect(fleetErrorText(null)).toBe(FLEET_FLASH.falha);
  expect(FLEET_FLASH.limiteolts).not.toMatch(/plano|preço|cobrança/i);
});

test("encerramento: erros, rótulos, comandos do dono com o nome entre aspas e carência (ADR-0050)", () => {
  expect(orgError(409, { detail: "organization_not_suspended" })).toBe("naosuspensa");
  expect(orgError(409, { detail: "organization_is_demo" })).toBe("demo");
  expect(orgError(409, { detail: "closure_exists" })).toBe("pedidoexiste");
  expect(orgError(404, { detail: "closure_not_found" })).toBe("sempedido");
  expect(orgError(404, { detail: "organization_not_found" })).toBe("naoencontrada");
  expect(orgError(409, { detail: "outra" })).toBe("falha");
  for (const k of ["naosuspensa", "demo", "pedidoexiste", "sempedido"]) expect(ORG_ERRORS[k], k).toBeTruthy();
  expect(ORG_FLASH.encerramentopedido).toContain("Nada foi apagado");
  expect(ORG_FLASH.encerramentocancelado).toBeTruthy();
  expect(ACTION_LABEL["platform.closure.requested"]).toBe("Encerramento pedido");
  expect(ACTION_LABEL["platform.closure.cancelled"]).toBe("Encerramento cancelado");
  expect(CLOSURE_STATE.requested).toBe("Pedido aberto");
  expect(historyText({ at: "x", action: "platform.closure.requested", actor: "Ana", detail: { reason: "Cliente saiu" } })).toBe("motivo: Cliente saiu");
  const id = "11111111-2222-3333-4444-555555555555";
  expect(closureCommands(id, "Provedor Teste")).toEqual({
    exportar: `org-export ${id} --out ARQUIVO.tar.gz`,
    encerrar: `org-close ${id} --confirm-name 'Provedor Teste' --export-file ARQUIVO.tar.gz`,
  });
  expect(shellQuote("D'Ávila; rm -rf /")).toBe(`'D'\\''Ávila; rm -rf /'`);        // apóstrofo e metacaracteres não escapam das aspas
  expect(shellQuote("$(id) `x`")).toBe("'$(id) `x`'");
  const now = Date.parse("2026-11-20T12:00:00Z");
  expect(graceOver({ earliest_close_at: "2026-11-20T11:59:59Z" }, now)).toBe(true);
  expect(graceOver({ earliest_close_at: "2026-11-20T12:00:01Z" }, now)).toBe(false);
  expect(graceOver(null, now)).toBe(false);
  expect(rowsDeleted({ olts: 3, onus: 10 })).toBe(13);
  expect(rowsDeleted(null)).toBe(0);
});
