import { failure, forward, readFields, reply } from "@/lib/mfa-bff";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  if (!UUID.test(id)) return reply({ error: "bad_request" }, 400);
  // password + o segundo fator do PRÓPRIO administrador (a API exige os dois e recusa quem não tem MFA ativo)
  const f = await readFields(req, [{ name: "password", min: 1, max: 256 }, { name: "code", min: 6, max: 32 }]);
  if (f instanceof Response) return f;
  const r = await forward(`/v1/members/${id}/mfa/reset`, { password: f.password, code: f.code });
  if (r.status === 200) return reply({ ok: true, revoked_sessions: (r.json as { revoked_sessions?: number } | null)?.revoked_sessions ?? 0 });
  if (r.status === 409) {  // motivos distintos para o painel; só mensagens fixas da API são reconhecidas
    const d = String((r.json as { detail?: string } | null)?.detail ?? "");
    const error = d.includes("other workspaces") ? "other_workspaces" : d.includes("enable your own MFA") ? "admin_needs_mfa" : d.includes("your own MFA") ? "self" : "conflict";
    return reply({ error }, 409);
  }
  if (r.status === 404) return reply({ error: "not_found" }, 404);
  if (r.status === 403) return reply({ error: "forbidden" }, 403);
  return failure(r.status, r.json);
}
