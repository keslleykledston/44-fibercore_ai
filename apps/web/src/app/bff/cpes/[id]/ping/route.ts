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
    if (!caps || !runs) return reply({ error: "failed" }, 502);
    // Lista fechada de campos (nada de `cpe_id`, `job_id`, `edge_support`, certificação...): no formato bruto da API, porque a tela o valida de novo e não aceita o objeto já tratado.
    const open = {
      bench_target: caps.bench_target, test: { offered: caps.offered, reason: caps.reason }, ready: caps.ready,
      targets: caps.targets.map((t) => ({ id: t.id, label: t.label, target_kind: t.target_kind, region: t.region, ready: t.ready })),
      shape: { repetitions: caps.repetitions, timeout_ms: caps.timeout_ms }, limits: { per_cpe_per_hour: caps.per_hour },
    };
    return reply({ caps: open, runs, run_seen });
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
