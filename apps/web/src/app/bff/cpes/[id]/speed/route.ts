import { apiSafe } from "@/lib/api";
import { reply } from "@/lib/mfa-bff";
import { readCaps, readRuns } from "@/lib/speed";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Capacidades do teste de banda deste aparelho + as últimas execuções. A API decide; aqui só o formato fechado e códigos estáveis. */
export async function GET(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  if (!UUID.test(id)) return reply({ error: "bad_request" }, 400);
  const [c, r] = await Promise.all([apiSafe<unknown>(`/v1/cpes/${id}/speed/capabilities`), apiSafe<unknown>(`/v1/cpes/${id}/speed/runs`)]);
  if (c.data && r.data) {
    const caps = readCaps(c.data), runs = readRuns(r.data);
    return caps && runs ? reply({ caps, runs }) : reply({ error: "failed" }, 502);
  }
  const st = c.status !== 200 ? c.status : r.status;
  if (st === 403) return reply({ error: "disabled" }, 403);
  if (st === 404) return reply({ error: "not_found" }, 404);
  if (st === 401) return reply({ error: "session" }, 401);
  return reply({ error: "failed" }, 502);
}

export const dynamic = "force-dynamic";
