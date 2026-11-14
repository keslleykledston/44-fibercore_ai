import { apiPost } from "@/lib/api";
import { reply } from "@/lib/mfa-bff";
import { UUID, isResponse, readJson, strList, teamFailure } from "@/lib/team-bff";

/** PATCH: renomear, trocar eventos, desligar/religar. DELETE: apagar o webhook (e as entregas dele). */
export async function PATCH(req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  if (!UUID.test(id)) return reply({ error: "bad_request" }, 400);
  const b = await readJson(req);
  if (isResponse(b)) return b;
  const out: Record<string, unknown> = {};
  if (b.name !== undefined) { if (typeof b.name !== "string" || b.name.trim().length < 2 || b.name.length > 60) return reply({ error: "bad_request" }, 400); out.name = b.name.trim(); }
  if (b.events !== undefined) { const ev = strList(b.events, 5); if (!ev || ev.length === 0) return reply({ error: "bad_request" }, 400); out.events = ev; }
  if (b.active !== undefined) { if (typeof b.active !== "boolean") return reply({ error: "bad_request" }, 400); out.active = b.active; }
  const r = await apiPost(`/v1/webhooks/${id}`, JSON.stringify(out), { "content-type": "application/json" }, "PATCH");
  return r.status === 200 ? reply({ ok: true }) : teamFailure(r.status, r.json);
}

export async function DELETE(req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  if (!UUID.test(id)) return reply({ error: "bad_request" }, 400);
  const b = await readJson(req);
  if (isResponse(b)) return b;
  const r = await apiPost(`/v1/webhooks/${id}`, undefined, {}, "DELETE");
  return r.status === 200 ? reply({ ok: true }) : teamFailure(r.status, r.json);
}

export const dynamic = "force-dynamic";
