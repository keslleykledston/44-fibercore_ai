import { apiPost } from "@/lib/api";
import { sameOrigin } from "@/lib/csrf";
import { reply } from "@/lib/mfa-bff";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const KEY = /^[A-Za-z0-9_.:-]{8,128}$/;

/** Pede UMA leitura rápida de qualidade (só lê o que o produto já tem: nenhum tráfego no aparelho, nenhum teste). A API decide tudo. */
export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }) {
  if (!sameOrigin(req)) return reply({ error: "forbidden" }, 403);
  const { id } = await ctx.params;
  if (!UUID.test(id)) return reply({ error: "bad_request" }, 400);
  const raw = await req.text();
  if (raw.length > 256) return reply({ error: "bad_request" }, 413);
  let b: { key?: unknown };
  try { b = JSON.parse(raw); } catch { return reply({ error: "bad_request" }, 400); }
  if (typeof b.key !== "string" || !KEY.test(b.key)) return reply({ error: "bad_request" }, 400);
  const r = await apiPost(`/v1/cpes/${id}/quality/runs`, JSON.stringify({ mode: "quick" }), { "content-type": "application/json", "Idempotency-Key": b.key });
  if (r.status === 201 || r.status === 200) return reply({ ok: true });
  if (r.status === 403) return reply({ error: String((r.json as { detail?: string } | null)?.detail) === "feature_disabled" ? "disabled" : "forbidden" }, 403);
  if (r.status === 404) return reply({ error: "not_found" }, 404);
  if (r.status === 401) return reply({ error: "session" }, 401);
  if (r.status === 409 || r.status === 422) return reply({ error: "bad_request" }, 400);
  return reply({ error: "failed" }, 502);
}

export const dynamic = "force-dynamic";
