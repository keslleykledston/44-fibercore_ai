import { apiPost } from "@/lib/api";
import { reply } from "@/lib/mfa-bff";
import { UUID, isResponse, readJson, teamFailure } from "@/lib/team-bff";

/** Revoga um token de API (vale na hora). */
export async function DELETE(req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  if (!UUID.test(id)) return reply({ error: "bad_request" }, 400);
  const b = await readJson(req);
  if (isResponse(b)) return b;
  const r = await apiPost(`/v1/api-tokens/${id}`, undefined, {}, "DELETE");
  return r.status === 200 ? reply({ ok: true }) : teamFailure(r.status, r.json);
}

export const dynamic = "force-dynamic";
