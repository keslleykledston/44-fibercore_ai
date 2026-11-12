import { expect, test } from "@playwright/test";
import { cursorQuery, decodeFlash, encodeFlash, inviteLabel, inviteUrl, orgError, ORG_ERRORS, stepUpError } from "../src/lib/platform";

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

test("o link do convite junta a origem pública e o token, sem barra repetida", () => {
  expect(inviteUrl("https://painel.exemplo.com/", TOKEN)).toBe(`https://painel.exemplo.com/convite/${TOKEN}`);
  expect(inviteUrl("http://127.0.0.1:3000", TOKEN)).toBe(`http://127.0.0.1:3000/convite/${TOKEN}`);
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
