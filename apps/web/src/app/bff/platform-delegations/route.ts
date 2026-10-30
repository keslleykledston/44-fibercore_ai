import { apiPost } from "@/lib/api";
import { readFields, reply } from "@/lib/mfa-bff";

/** Concede o acesso temporário ao suporte da plataforma (a API decide; aqui só formato e códigos estáveis). */
export async function POST(req: Request) {
  const f = await readFields(req, [{ name: "email", min: 3, max: 254 }, { name: "reason", min: 10, max: 300 }, { name: "hours", min: 1, max: 1 }]);
  if (f instanceof Response) return f;
  const hours = Number(f.hours);
  if (!/^[1-8]$/.test(f.hours) || !f.email.includes("@")) return reply({ error: "bad_request" }, 400);
  const r = await apiPost("/v1/platform-delegations", JSON.stringify({ email: f.email.trim(), reason: f.reason, hours }), { "content-type": "application/json" });
  if (r.status === 201) {
    const j = r.json as { expires_at?: string; replaced?: number } | null;
    return reply({ ok: true, expires_at: j?.expires_at ?? null, replaced: j?.replaced ?? 0 }, 201);
  }
  const detail = String((r.json as { detail?: string } | null)?.detail ?? "");
  if (r.status === 403 && detail === "mfa_recent_required") return reply({ error: "mfa_recent_required" }, 403);
  if (r.status === 404) return reply({ error: "operator_not_found" }, 404);
  if (r.status === 409 && detail === "already_member") return reply({ error: "already_member" }, 409);
  if (r.status === 422) return reply({ error: detail === "cannot_delegate_to_self" ? "cannot_delegate_to_self" : "bad_request" }, detail === "cannot_delegate_to_self" ? 422 : 400);
  if (r.status === 401) return reply({ error: "session" }, 401);
  if (r.status === 403) return reply({ error: "forbidden" }, 403);
  return reply({ error: "failed" }, 502);
}

export const dynamic = "force-dynamic";
