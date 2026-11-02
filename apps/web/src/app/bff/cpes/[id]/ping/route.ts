import { apiSafe } from "@/lib/api";
import { reply } from "@/lib/mfa-bff";
import { readPingCaps, readPingRuns } from "@/lib/ping";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Capacidades do teste de ping deste aparelho + as últimas execuções. A API decide; aqui só o formato fechado e códigos estáveis. */
export async function GET(req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  if (!UUID.test(id)) return reply({ error: "bad_request" }, 400);
  // `?run=` = a execução de um pedido aceito que a tela espera ver: a lista só traz as mais recentes, então a existência dela é perguntada à API pelo id (200 = existe, 404 = não existe; outro erro = não se sabe)
  const asked = new URL(req.url).searchParams.get("run");
  const run = asked && UUID.test(asked) ? asked : null;
  const [c, r, one] = await Promise.all([apiSafe<unknown>(`/v1/cpes/${id}/ping/capabilities`), apiSafe<unknown>(`/v1/cpes/${id}/ping/runs`), run ? apiSafe<unknown>(`/v1/cpes/${id}/ping/runs/${run}`) : Promise.resolve(null)]);
  if (c.data && r.data) {
    const caps = readPingCaps(c.data), runs = readPingRuns(r.data);
    const run_seen = one ? (one.status === 200 ? true : one.status === 404 ? false : null) : null;
    // validado aqui E de novo na tela: o corpo que segue é o da API (a tela lê o formato bruto), nunca o objeto já tratado (a tela o recusaria)
    return caps && runs ? reply({ caps: c.data, runs: (r.data as { items: unknown[] }).items, run_seen }) : reply({ error: "failed" }, 502);
  }
  const bad = c.status !== 200 ? c : r;   // o status/código da leitura que FALHOU (uma delas respondeu erro; se as duas responderam 200, o corpo é que não tem o formato)
  const st = c.status === 200 && r.status === 200 ? 502 : bad.status;
  // só o código explícito da API vira "recurso desligado"; qualquer outro 403 é falta de permissão
  if (st === 403) return reply({ error: bad.detail === "feature_disabled" ? "disabled" : "forbidden" }, 403);
  if (st === 404) return reply({ error: "not_found" }, 404);
  if (st === 401) return reply({ error: "session" }, 401);
  return reply({ error: "failed" }, 502);
}

export const dynamic = "force-dynamic";
