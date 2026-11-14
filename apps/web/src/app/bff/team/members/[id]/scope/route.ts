import { apiPost } from "@/lib/api";
import { reply } from "@/lib/mfa-bff";
import { UUID, isResponse, readJson, strList, teamFailure } from "@/lib/team-bff";

/** Escopo de uma pessoa (ADR-0049 D2). GET: o escopo atual e as opções (sites e OLTs); PUT: define; DELETE: devolve o provedor inteiro. */
export async function GET(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  if (!UUID.test(id)) return reply({ error: "bad_request" }, 400);
  const r = await apiPost(`/v1/team/members/${id}/scope`, undefined, {}, "GET");
  return r.status === 200 ? reply(r.json) : teamFailure(r.status, r.json);
}

export async function PUT(req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  if (!UUID.test(id)) return reply({ error: "bad_request" }, 400);
  const b = await readJson(req, 16_000);
  if (isResponse(b)) return b;
  const pops = strList(b.pop_ids ?? [], 200), olts = strList(b.olt_ids ?? [], 200);
  if (!pops || !olts || ![...pops, ...olts].every((x) => UUID.test(x))) return reply({ error: "bad_request" }, 400);
  const r = await apiPost(`/v1/team/members/${id}/scope`, JSON.stringify({ pop_ids: pops, olt_ids: olts }), { "content-type": "application/json" }, "PUT");
  return r.status === 200 ? reply({ ok: true }) : teamFailure(r.status, r.json);
}

export async function DELETE(req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  if (!UUID.test(id)) return reply({ error: "bad_request" }, 400);
  const b = await readJson(req);
  if (isResponse(b)) return b;
  const r = await apiPost(`/v1/team/members/${id}/scope`, undefined, {}, "DELETE");
  return r.status === 200 ? reply({ ok: true }) : teamFailure(r.status, r.json);
}

export const dynamic = "force-dynamic";
