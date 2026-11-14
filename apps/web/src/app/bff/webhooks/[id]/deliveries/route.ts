import { apiPost } from "@/lib/api";
import { reply } from "@/lib/mfa-bff";
import { UUID, teamFailure } from "@/lib/team-bff";

/** Entregas recentes de um webhook (sem a carga: só estado e classe do erro). */
export async function GET(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  if (!UUID.test(id)) return reply({ error: "bad_request" }, 400);
  const r = await apiPost(`/v1/webhooks/${id}/deliveries`, undefined, {}, "GET");
  return r.status === 200 ? reply(r.json) : teamFailure(r.status, r.json);
}

export const dynamic = "force-dynamic";
