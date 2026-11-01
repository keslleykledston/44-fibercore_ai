import { apiPost } from "@/lib/api";
import { sameOrigin } from "@/lib/csrf";
import { reply } from "@/lib/mfa-bff";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const KEY = /^[A-Za-z0-9_.:-]{8,128}$/;
const TG = /^[a-z0-9][a-z0-9-]{1,30}$/;

/** Pede UM teste de ping. Só o nome lógico do destino; nenhum endereço passa por aqui. A API decide tudo e devolve o motivo da recusa em código estável. */
export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }) {
  if (!sameOrigin(req)) return reply({ error: "forbidden" }, 403);
  const { id } = await ctx.params;
  if (!UUID.test(id)) return reply({ error: "bad_request" }, 400);
  const raw = await req.text();
  if (raw.length > 512) return reply({ error: "bad_request" }, 413);
  let b: { key?: unknown; target_id?: unknown };
  try { b = JSON.parse(raw); } catch { return reply({ error: "bad_request" }, 400); }
  if (typeof b.key !== "string" || !KEY.test(b.key) || typeof b.target_id !== "string" || !TG.test(b.target_id)) return reply({ error: "bad_request" }, 400);
  const r = await apiPost(`/v1/cpes/${id}/ping/runs`, JSON.stringify({ target_id: b.target_id }), { "content-type": "application/json", "Idempotency-Key": b.key });
  const j = r.json as { outcome?: string; reason?: string | null; detail?: string } | null;
  if (r.status === 201 || r.status === 200) return reply({ ok: true, outcome: j?.outcome === "existing" ? "existing" : "submitted" });
  if (r.status === 409 && j?.outcome === "blocked" && typeof j.reason === "string" && /^[a-z][a-z0-9_]{0,59}$/.test(j.reason)) return reply({ error: "blocked", reason: j.reason }, 409);
  if (r.status === 403) return reply({ error: j?.detail === "feature_disabled" ? "disabled" : "forbidden" }, 403);
  if (r.status === 404) return reply({ error: "not_found" }, 404);
  if (r.status === 401) return reply({ error: "session" }, 401);
  if (r.status === 422) return reply({ error: "bad_request" }, 400);
  return reply({ error: "failed" }, 502);
}

export const dynamic = "force-dynamic";
