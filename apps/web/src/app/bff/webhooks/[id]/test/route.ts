import { apiPost } from "@/lib/api";
import { reply } from "@/lib/mfa-bff";
import { UUID, isResponse, readJson, teamFailure } from "@/lib/team-bff";

/** Enfileira uma entrega de teste (carga fixa e inofensiva). */
export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  if (!UUID.test(id)) return reply({ error: "bad_request" }, 400);
  const b = await readJson(req);
  if (isResponse(b)) return b;
  const r = await apiPost(`/v1/webhooks/${id}/test`, undefined, {});
  return r.status === 202 ? reply({ ok: true }, 202) : teamFailure(r.status, r.json);
}

export const dynamic = "force-dynamic";
