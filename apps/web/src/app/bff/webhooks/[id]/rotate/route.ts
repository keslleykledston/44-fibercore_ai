import { apiPost } from "@/lib/api";
import { reply } from "@/lib/mfa-bff";
import { UUID, isResponse, readJson, teamFailure } from "@/lib/team-bff";

/** Gira o segredo (o antigo para de valer na hora). O novo vem UMA vez. */
export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  if (!UUID.test(id)) return reply({ error: "bad_request" }, 400);
  const b = await readJson(req);
  if (isResponse(b)) return b;
  const r = await apiPost(`/v1/webhooks/${id}/rotate-secret`, undefined, {});
  return r.status === 200 ? reply({ ok: true, secret: (r.json as { secret?: string }).secret }) : teamFailure(r.status, r.json);
}

export const dynamic = "force-dynamic";
