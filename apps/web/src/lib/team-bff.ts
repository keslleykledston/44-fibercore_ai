import { reply } from "@/lib/mfa-bff";

/** Códigos estáveis da API que a tela de equipe repassa; qualquer outro vira uma resposta genérica (nunca texto da API). */
const PASS = new Set([
  "role_cannot_grant", "role_not_assignable", "target_role_protected", "cannot_remove_self", "use_change_password", "member_not_found", "invite_not_found", "invite_not_open",
  "already_member", "last_isp_admin", "account_shared", "email_invalid", "name_invalid", "reason_required", "conflict_retry", "mfa_recent_required",
  // ADR-0048 a 0051 (e-mail, política, escopo, tokens, webhooks): códigos estáveis da API repassados como estão
  "email_not_configured", "limit_reached", "cannot_scope_self", "role_not_scopable", "scope_invalid", "scope_target_not_found", "clear_scope_first", "mfa_unavailable",
  "enable_your_mfa_first", "role_invalid", "permission_not_allowed", "name_invalid", "token_limit", "token_not_found", "webhook_limit", "webhook_not_found", "webhooks_unavailable",
  "event_not_allowed", "nothing_to_change", "url_too_long", "url_invalid", "url_must_be_https", "url_host_must_be_a_name", "url_host_not_public",
]);

export function teamFailure(status: number, json: unknown) {
  const detail = String((json as { detail?: string } | null)?.detail ?? "");
  if (PASS.has(detail)) return reply({ error: detail }, [403, 404, 409, 422, 503].includes(status) ? status : 409);
  if (status === 401) return reply({ error: "session" }, 401);
  if (status === 403) return reply({ error: "forbidden" }, 403);
  if (status === 404) return reply({ error: "member_not_found" }, 404);
  if (status === 422) return reply({ error: "bad_request" }, 400);
  if (status === 503) return reply({ error: "unavailable" }, 503);
  return reply({ error: "failed" }, 502);
}

/** Corpo JSON pequeno e validado; devolve a resposta de erro ou o objeto. Só same-origin. */
export async function readJson(req: Request, max = 4096): Promise<Response | Record<string, unknown>> {
  const { sameOrigin } = await import("@/lib/csrf");
  if (!sameOrigin(req)) return reply({ error: "forbidden" }, 403);
  const raw = await req.text();
  if (raw.length > max) return reply({ error: "bad_request" }, 413);
  try { const j = JSON.parse(raw || "{}"); return j && typeof j === "object" && !Array.isArray(j) ? (j as Record<string, unknown>) : reply({ error: "bad_request" }, 400); }
  catch { return reply({ error: "bad_request" }, 400); }
}
export const isResponse = (x: unknown): x is Response => x instanceof Response;
export const strList = (v: unknown, max: number): string[] | null =>
  Array.isArray(v) && v.length <= max && v.every((x) => typeof x === "string" && x.length <= 80) ? (v as string[]) : null;

export const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export const ROLE = /^[a-z][a-z0-9_]{0,31}$/;
