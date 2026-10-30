import { apiSafe } from "@/lib/api";
import { reply } from "@/lib/mfa-bff";
import type { OltQueryCatalog } from "@/lib/olt-queries";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Catálogo de consultas da OLT como este usuário o vê (só leitura). */
export async function GET(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  if (!UUID.test(id)) return reply({ error: "bad_request" }, 400);
  const r = await apiSafe<OltQueryCatalog>(`/v1/olts/${id}/queries`);
  if (r.data) return reply({ enabled: r.data.enabled, limits: r.data.limits, items: r.data.items.map((i) => ({ id: i.id, title: i.title, scope: i.scope, fields: i.fields, validated: i.validated, offered: i.offered, reason: i.reason })) });
  if (r.status === 404) return reply({ error: "not_found" }, 404);
  if (r.status === 403) return reply({ error: "forbidden" }, 403);
  return reply({ error: "failed" }, 502);
}

export const dynamic = "force-dynamic";
