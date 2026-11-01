import { apiSafe } from "@/lib/api";
import { reply } from "@/lib/mfa-bff";
import { readCaps, readRuns } from "@/lib/speed";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Capacidades do teste de banda deste aparelho + as últimas execuções. A API decide; aqui só o formato fechado e códigos estáveis. */
export async function GET(req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  if (!UUID.test(id)) return reply({ error: "bad_request" }, 400);
  // `?run=` = a execução de um pedido aceito que a tela espera ver: a lista só traz as mais recentes, então a existência dela é perguntada à API pelo id (200 = existe, 404 = não existe; outro erro = não se sabe)
  const asked = new URL(req.url).searchParams.get("run");
  const run = asked && UUID.test(asked) ? asked : null;
  const [c, r, one] = await Promise.all([apiSafe<unknown>(`/v1/cpes/${id}/speed/capabilities`), apiSafe<unknown>(`/v1/cpes/${id}/speed/runs`), run ? apiSafe<unknown>(`/v1/cpes/${id}/speed/runs/${run}`) : Promise.resolve(null)]);
  if (c.data && r.data) {
    const caps = readCaps(c.data), runs = readRuns(r.data);
    const run_seen = one ? (one.status === 200 ? true : one.status === 404 ? false : null) : null;
    return caps && runs ? reply({ caps, runs, run_seen }) : reply({ error: "failed" }, 502);
  }
  const st = c.status !== 200 ? c.status : r.status;
  if (st === 403) return reply({ error: "disabled" }, 403);
  if (st === 404) return reply({ error: "not_found" }, 404);
  if (st === 401) return reply({ error: "session" }, 401);
  return reply({ error: "failed" }, 502);
}

export const dynamic = "force-dynamic";
