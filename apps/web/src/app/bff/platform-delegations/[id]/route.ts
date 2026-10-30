import { apiPost } from "@/lib/api";
import { reply } from "@/lib/mfa-bff";
import { sameOrigin } from "@/lib/csrf";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Revoga o acesso temporário. O botão manda POST (formulário do servidor não tem DELETE): a API recebe o DELETE. */
export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }) {
  if (!sameOrigin(req)) return reply({ error: "forbidden" }, 403);
  const { id } = await ctx.params;
  if (!UUID.test(id)) return reply({ error: "bad_request" }, 400);
  const r = await apiPost(`/v1/platform-delegations/${id}`, undefined, {}, "DELETE");
  if (r.status === 200) return reply({ ok: true });
  const detail = String((r.json as { detail?: string } | null)?.detail ?? "");
  if (r.status === 403 && detail === "mfa_recent_required") return reply({ error: "mfa_recent_required" }, 403);
  if (r.status === 404) return reply({ error: "not_found" }, 404);
  if (r.status === 409) return reply({ error: "not_active" }, 409);
  if (r.status === 401) return reply({ error: "session" }, 401);
  if (r.status === 403) return reply({ error: "forbidden" }, 403);
  return reply({ error: "failed" }, 502);
}

export const dynamic = "force-dynamic";
