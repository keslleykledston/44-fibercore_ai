import { apiPost } from "@/lib/api";
import { sameOrigin } from "@/lib/csrf";
import { reply } from "@/lib/mfa-bff";
import { PROFILES } from "@/lib/speed";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const KEY = /^[A-Za-z0-9_.:-]{8,128}$/;
const EP = /^[a-z0-9][a-z0-9-]{1,30}$/;

/** Pede UM teste (um sentido). Só nomes lógicos: destino e tamanho de uma lista; nenhum endereço passa por aqui. A API decide tudo e devolve o motivo da recusa em código estável. */
export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }) {
  if (!sameOrigin(req)) return reply({ error: "forbidden" }, 403);
  const { id } = await ctx.params;
  if (!UUID.test(id)) return reply({ error: "bad_request" }, 400);
  const raw = await req.text();
  if (raw.length > 1024) return reply({ error: "bad_request" }, 413);
  let b: { key?: unknown; direction?: unknown; endpoint_id?: unknown; profile?: unknown; group_id?: unknown };
  try { b = JSON.parse(raw); } catch { return reply({ error: "bad_request" }, 400); }
  if (typeof b.key !== "string" || !KEY.test(b.key) || (b.direction !== "download" && b.direction !== "upload") || typeof b.endpoint_id !== "string" || !EP.test(b.endpoint_id) ||
    typeof b.profile !== "string" || !(PROFILES as readonly string[]).includes(b.profile) || (b.group_id !== undefined && (typeof b.group_id !== "string" || !UUID.test(b.group_id)))) return reply({ error: "bad_request" }, 400);
  const body = JSON.stringify({ direction: b.direction, endpoint_id: b.endpoint_id, profile: b.profile, ...(b.group_id ? { group_id: b.group_id } : {}) });
  const r = await apiPost(`/v1/cpes/${id}/speed/runs`, body, { "content-type": "application/json", "Idempotency-Key": b.key });
  const j = r.json as { outcome?: string; reason?: string | null } | null;
  if (r.status === 201 || r.status === 200) return reply({ ok: true, outcome: j?.outcome === "existing" ? "existing" : "submitted" });
  if (r.status === 409 && j?.outcome === "blocked" && typeof j.reason === "string" && /^[a-z][a-z0-9_]{0,59}$/.test(j.reason)) return reply({ error: "blocked", reason: j.reason }, 409);
  if (r.status === 403) return reply({ error: String((j as { detail?: string } | null)?.detail) === "feature_disabled" ? "disabled" : "forbidden" }, 403);
  if (r.status === 404) return reply({ error: "not_found" }, 404);
  if (r.status === 401) return reply({ error: "session" }, 401);
  if (r.status === 422) return reply({ error: "bad_request" }, 400);
  return reply({ error: "failed" }, 502);
}

export const dynamic = "force-dynamic";
