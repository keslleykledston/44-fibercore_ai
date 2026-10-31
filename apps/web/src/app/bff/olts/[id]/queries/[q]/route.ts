import { apiPost } from "@/lib/api";
import { sameOrigin } from "@/lib/csrf";
import { reply } from "@/lib/mfa-bff";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const QID = /^[a-z]+(\.[a-z]+)+$/;
const KEY = /^[A-Za-z0-9_.:-]{8,128}$/;
const KNOWN = new Set(["olt_query_disabled", "query_not_enabled", "olt_without_edge", "not_permitted"]);

/** Pede UMA consulta somente leitura (sem parâmetros: só as globais são oferecidas). A API decide tudo; aqui só formato e códigos estáveis. */
export async function POST(req: Request, ctx: { params: Promise<{ id: string; q: string }> }) {
  if (!sameOrigin(req)) return reply({ error: "forbidden" }, 403);
  const { id, q } = await ctx.params;
  if (!UUID.test(id) || !QID.test(q)) return reply({ error: "bad_request" }, 400);
  const raw = await req.text();
  if (raw.length > 512) return reply({ error: "bad_request" }, 413);
  let body: { key?: unknown; refresh?: unknown };
  try { body = JSON.parse(raw); } catch { return reply({ error: "bad_request" }, 400); }
  if (typeof body.key !== "string" || !KEY.test(body.key)) return reply({ error: "bad_request" }, 400);
  const r = await apiPost(`/v1/olts/${id}/queries/${q}`, JSON.stringify({ params: {}, refresh: body.refresh === true }), { "content-type": "application/json", "Idempotency-Key": body.key });
  if (r.status === 200) {
    const j = r.json as { outcome?: string; job?: { id?: string; status?: string }; cached?: { data?: unknown; observed_at?: string; age_seconds?: number } } | null;
    if (j?.outcome === "cached" && j.cached && Number.isInteger(j.cached.age_seconds)) {
      return reply({ ok: true, outcome: "cached", data: j.cached.data ?? null, observed_at: j.cached.observed_at ?? null, age_seconds: j.cached.age_seconds });
    }
    return reply({ ok: true, outcome: j?.outcome === "existing" ? "existing" : "submitted", job_id: j?.job?.id ?? null });
  }
  const detail = String((r.json as { detail?: string } | null)?.detail ?? "");
  if (r.status === 409 && KNOWN.has(detail)) return reply({ error: detail }, 409);
  if (r.status === 429) return reply({ error: detail === "olt_query_refresh_quota" ? "olt_query_refresh_quota" : "olt_query_quota" }, 429);
  if (r.status === 404) return reply({ error: "not_found" }, 404);
  if (r.status === 401) return reply({ error: "session" }, 401);
  if (r.status === 403) return reply({ error: "forbidden" }, 403);
  if (r.status === 422) return reply({ error: "bad_request" }, 400);
  return reply({ error: "failed" }, 502);
}

export const dynamic = "force-dynamic";
