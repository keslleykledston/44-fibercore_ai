import { reply } from "@/lib/mfa-bff";

/** Códigos estáveis da API que a tela de equipe repassa; qualquer outro vira uma resposta genérica (nunca texto da API). */
const PASS = new Set([
  "role_cannot_grant", "role_not_assignable", "target_role_protected", "cannot_remove_self", "use_change_password", "member_not_found", "invite_not_found", "invite_not_open",
  "already_member", "last_isp_admin", "account_shared", "email_invalid", "name_invalid", "reason_required", "conflict_retry", "mfa_recent_required",
]);

export function teamFailure(status: number, json: unknown) {
  const detail = String((json as { detail?: string } | null)?.detail ?? "");
  if (PASS.has(detail)) return reply({ error: detail }, [403, 404, 409, 422].includes(status) ? status : 409);
  if (status === 401) return reply({ error: "session" }, 401);
  if (status === 403) return reply({ error: "forbidden" }, 403);
  if (status === 404) return reply({ error: "member_not_found" }, 404);
  if (status === 422) return reply({ error: "bad_request" }, 400);
  if (status === 503) return reply({ error: "unavailable" }, 503);
  return reply({ error: "failed" }, 502);
}

export const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export const ROLE = /^[a-z][a-z0-9_]{0,31}$/;
