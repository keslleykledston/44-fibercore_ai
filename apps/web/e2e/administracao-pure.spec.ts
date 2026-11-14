import { expect, test } from "@playwright/test";
import { DELIVERY_ERROR, EVENT_LABEL, PERMISSION_LABEL, SIGNATURE_EXAMPLE, clampDays, failureText, urlProblem } from "../src/lib/integrations";
import { affected, canSaveScope, optionsLabel, roleName, sameSet, scopeBadge, scopeNotice, toggle } from "../src/lib/orgSecurity";
import { TEAM_ERROR } from "../src/lib/team";

// Administração da organização (ADR-0048 a 0051): textos e regras PURAS. Sem navegador nem API.

test("URL de webhook: só https com NOME público; a forma é conferida aqui e a API decide de novo", () => {
  expect(urlProblem("https://hooks.exemplo.com.br/fibercore")).toBeNull();
  expect(urlProblem("https://hooks.exemplo.com.br:8443/x?a=1")).toBeNull();
  expect(urlProblem("http://hooks.exemplo.com.br/x")).toBe("url_must_be_https");
  expect(urlProblem("https://10.0.0.5/x")).toBe("url_host_must_be_a_name");
  expect(urlProblem("https://169.254.169.254/latest")).toBe("url_host_must_be_a_name");
  expect(urlProblem("https://[::1]/x")).toBe("url_host_must_be_a_name");
  expect(urlProblem("https://localhost/x")).toBe("url_host_not_public");
  expect(urlProblem("https://intranet/x")).toBe("url_host_not_public");
  expect(urlProblem("https://db.internal/x")).toBe("url_host_not_public");
  expect(urlProblem("https://a.local/x")).toBe("url_host_not_public");
  expect(urlProblem("https://user:pw@hooks.exemplo.com.br/x")).toBe("url_invalid");
  expect(urlProblem("isso não é url")).toBe("url_invalid");
  for (const code of ["url_must_be_https", "url_host_must_be_a_name", "url_host_not_public", "url_invalid"]) expect(TEAM_ERROR[code]).toMatch(/\S/);
});

test("todo código novo da API tem texto em português e nenhum código técnico chega à tela", () => {
  const codes = ["email_not_configured", "limit_reached", "cannot_scope_self", "role_not_scopable", "scope_invalid", "scope_target_not_found", "clear_scope_first", "mfa_unavailable",
    "enable_your_mfa_first", "role_invalid", "permission_not_allowed", "token_limit", "token_not_found", "webhook_limit", "webhook_not_found", "webhooks_unavailable", "event_not_allowed", "nothing_to_change"];
  for (const c of codes) { expect(TEAM_ERROR[c], c).toMatch(/\S/); expect(TEAM_ERROR[c]).not.toMatch(/_[a-z]+_|[a-z]+:[a-z]+/); }
  for (const t of Object.values(DELIVERY_ERROR)) expect(t).toMatch(/\S/);
});

test("tokens: toda permissão da lista tem rótulo; a validade é limitada a 1..365", () => {
  for (const p of ["inventory:read", "incidents:read", "fleet:read", "discovery:read", "diagnostics:quality_read"]) expect(PERMISSION_LABEL[p].label).toMatch(/\S/);
  expect(Object.values(PERMISSION_LABEL).map((x) => x.label).join(" ")).not.toMatch(/:read/);
  expect([clampDays(0), clampDays(90), clampDays(999), clampDays(Number.NaN), clampDays(12.7)]).toEqual([1, 90, 365, 90, 12]);
  expect(EVENT_LABEL["incident.opened"]).toBe("Incidente aberto");
});

test("falha de entrega: só a classe vira frase; o resto vira frase genérica e nada de URL ou segredo", () => {
  expect(failureText("address_not_public")).toContain("público");
  expect(failureText("http_error")).toContain("erro");
  expect(failureText("algo_novo")).toBe("falha na entrega");
  expect(failureText(null)).toBeNull();
  expect(SIGNATURE_EXAMPLE).toContain("compare_digest");
  expect(SIGNATURE_EXAMPLE).not.toMatch(/whsec_/);
});

test("política de MFA: o piso não sai, só se acrescenta; conta quem será levado a cadastrar", () => {
  const policy = { floor: ["access_manager"], members_without_mfa: { access_manager: 1, support: 3, engineer: 2 } };
  expect(affected(policy, [])).toBe(1);                       // o piso já conta
  expect(affected(policy, ["support"])).toBe(4);
  expect(affected(policy, ["support", "engineer"])).toBe(6);
  expect(affected(policy, ["auditor"])).toBe(1);
  expect(sameSet(["a", "b"], ["b", "a"])).toBe(true);
  expect(sameSet(["a"], ["a", "b"])).toBe(false);
  expect(roleName("isp_admin")).toBe("Administrador do provedor");
  expect(roleName("papel_novo")).toBe("papel_novo");
});

test("escopo: o selo, o aviso e a seleção dizem o que está restrito, sem repetir id e sem salvar vazio", () => {
  expect(scopeBadge(undefined)).toBe("Escopo: provedor inteiro");
  expect(scopeBadge({ restricted: false, pops: 0, olts: 0 })).toBe("Escopo: provedor inteiro");
  expect(scopeBadge({ restricted: true, pops: 1, olts: 0 })).toBe("Restrito: 1 site");
  expect(scopeBadge({ restricted: true, pops: 2, olts: 3 })).toBe("Restrito: 2 sites, 3 OLTs");
  expect(scopeBadge({ restricted: true, pops: 0, olts: 1 })).toBe("Restrito: 1 OLT");
  expect(scopeNotice(1)).toBe("Seu acesso é restrito a 1 OLT.");
  expect(scopeNotice(2)).toBe("Seu acesso é restrito a 2 OLTs.");
  expect(scopeNotice(0)).toBe("Seu acesso é restrito a 0 OLTs.");
  expect(toggle(["a"], "b", true)).toEqual(["a", "b"]);
  expect(toggle(["a", "b"], "b", true)).toEqual(["a", "b"]);
  expect(toggle(["a", "b"], "a", false)).toEqual(["b"]);
  expect(canSaveScope([], [])).toBe(false);
  expect(canSaveScope(["p"], [])).toBe(true);
  expect(canSaveScope(Array(201).fill("x"), [])).toBe(false);
  const o = { pops: [{ id: "p1", name: "Site A" }], olts: [{ id: "o1", name: "OLT-1", pop_id: "p1" }] };
  expect([optionsLabel(o, "o1"), optionsLabel(o, "p1"), optionsLabel(o, "zzz")]).toEqual(["OLT-1", "Site A", "(removido)"]);
});
