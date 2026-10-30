import { apiPost } from "@/lib/api";
import { sameOrigin } from "@/lib/csrf";
import { reply } from "@/lib/mfa-bff";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const KNOWN = new Set(["role_cannot_authorize", "authorization_not_open", "owner_authorization", "mfa_recent_required"]);

/** Encerra uma autorização de bancada dada pela API (o botão manda POST; a API recebe o DELETE). */
export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }) {
  if (!sameOrigin(req)) return reply({ error: "forbidden" }, 403);
  const { id } = await ctx.params;
  if (!UUID.test(id)) return reply({ error: "bad_request" }, 400);
  const r = await apiPost(`/v1/bench/authorizations/${id}`, undefined, {}, "DELETE");
  if (r.status === 200) return reply({ ok: true });
  const detail = String((r.json as { detail?: string } | null)?.detail ?? "");
  if ([403, 409].includes(r.status) && KNOWN.has(detail)) return reply({ error: detail }, r.status);
  if (r.status === 404) return reply({ error: "authorization_not_found" }, 404);
  if (r.status === 401) return reply({ error: "session" }, 401);
  if (r.status === 403) return reply({ error: "forbidden" }, 403);
  if (r.status === 503) return reply({ error: "unavailable" }, 503);
  return reply({ error: "failed" }, 502);
}

export const dynamic = "force-dynamic";
