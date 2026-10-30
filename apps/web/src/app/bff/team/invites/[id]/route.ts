import { apiPost } from "@/lib/api";
import { sameOrigin } from "@/lib/csrf";
import { reply } from "@/lib/mfa-bff";
import { UUID, teamFailure } from "@/lib/team-bff";

/** Gera um novo link (renew) ou cancela (cancel) um convite pendente. */
export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }) {
  if (!sameOrigin(req)) return reply({ error: "forbidden" }, 403);
  const { id } = await ctx.params;
  if (!UUID.test(id)) return reply({ error: "bad_request" }, 400);
  let b: { action?: unknown };
  try { b = JSON.parse(await req.text()); } catch { return reply({ error: "bad_request" }, 400); }
  if (b.action === "renew") {
    const r = await apiPost(`/v1/team/invites/${id}/renew`, undefined, {});
    if (r.status === 201) {
      const j = r.json as { id?: string; token?: string; expires_at?: string; role_label?: string; email?: string };
      return reply({ ok: true, id: j.id, token: j.token, expires_at: j.expires_at, role_label: j.role_label, email: j.email }, 201);
    }
    return teamFailure(r.status, r.json);
  }
  if (b.action === "cancel") {
    const r = await apiPost(`/v1/team/invites/${id}`, undefined, {}, "DELETE");
    return r.status === 200 ? reply({ ok: true }) : teamFailure(r.status, r.json);
  }
  return reply({ error: "bad_request" }, 400);
}

export const dynamic = "force-dynamic";
