import { apiPost } from "@/lib/api";
import { sameOrigin } from "@/lib/csrf";
import { reply } from "@/lib/mfa-bff";
import { UUID, teamFailure } from "@/lib/team-bff";

/** Ações sobre uma pessoa da equipe: reset (link para ela trocar a senha) e remove (tirar da equipe, com motivo). */
export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }) {
  if (!sameOrigin(req)) return reply({ error: "forbidden" }, 403);
  const { id } = await ctx.params;
  if (!UUID.test(id)) return reply({ error: "bad_request" }, 400);
  let b: { action?: unknown; reason?: unknown };
  try { b = JSON.parse(await req.text()); } catch { return reply({ error: "bad_request" }, 400); }
  if (b.action === "reset") {
    const r = await apiPost(`/v1/team/members/${id}/password-reset`, undefined, {});
    if (r.status === 201) {
      const j = r.json as { token?: string; expires_at?: string };
      return reply({ ok: true, token: j.token, expires_at: j.expires_at }, 201);
    }
    return teamFailure(r.status, r.json);
  }
  if (b.action === "remove") {
    if (typeof b.reason !== "string" || b.reason.trim().length < 3 || b.reason.length > 200) return reply({ error: "reason_required" }, 422);
    const r = await apiPost(`/v1/team/members/${id}/remove`, JSON.stringify({ reason: b.reason.trim() }), { "content-type": "application/json" });
    return r.status === 200 ? reply({ ok: true }) : teamFailure(r.status, r.json);
  }
  return reply({ error: "bad_request" }, 400);
}

export const dynamic = "force-dynamic";
