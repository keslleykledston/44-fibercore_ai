import { apiPost } from "@/lib/api";
import { readFields, reply } from "@/lib/mfa-bff";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const KNOWN = new Set(["cannot_change_own_role", "role_cannot_grant", "role_not_assignable", "target_role_protected", "role_unchanged", "last_isp_admin", "conflict_retry", "reason_required"]);

/** Troca o papel de um membro (a API decide tudo; aqui só se valida o formato e se repassam códigos estáveis, nunca texto da API). */
export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  if (!UUID.test(id)) return reply({ error: "bad_request" }, 400);
  const f = await readFields(req, [{ name: "role", min: 1, max: 32 }, { name: "reason", min: 3, max: 200 }]);
  if (f instanceof Response) return f;
  if (!/^[a-z][a-z0-9_]{0,31}$/.test(f.role)) return reply({ error: "bad_request" }, 400);
  const r = await apiPost(`/v1/members/${id}/role`, JSON.stringify({ role: f.role, reason: f.reason }), { "content-type": "application/json" }, "PUT");
  if (r.status === 200) {
    const j = r.json as { previous_role?: string; revoked_sessions?: number } | null;
    return reply({ ok: true, previous_role: j?.previous_role ?? null, revoked_sessions: j?.revoked_sessions ?? 0 });
  }
  const detail = String((r.json as { detail?: string } | null)?.detail ?? "");
  if ([403, 409].includes(r.status) && KNOWN.has(detail)) return reply({ error: detail === "reason_required" ? "bad_request" : detail }, r.status);
  if (r.status === 404) return reply({ error: "not_found" }, 404);
  if (r.status === 401) return reply({ error: "session" }, 401);
  if (r.status === 403) return reply({ error: "forbidden" }, 403);
  if (r.status === 422) return reply({ error: "bad_request" }, 400);
  if (r.status === 503) return reply({ error: "unavailable" }, 503);
  return reply({ error: "failed" }, 502);
}

export const dynamic = "force-dynamic";
