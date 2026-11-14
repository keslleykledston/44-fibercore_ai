import { apiPost } from "@/lib/api";
import { reply } from "@/lib/mfa-bff";
import { isResponse, readJson, strList, teamFailure } from "@/lib/team-bff";

/** Cria um token de API (ADR-0051 D1). A resposta traz o token UMA vez; o painel não o guarda em lugar nenhum. */
export async function POST(req: Request) {
  const b = await readJson(req);
  if (isResponse(b)) return b;
  const perms = strList(b.permissions, 10);
  const days = typeof b.days === "number" && Number.isInteger(b.days) && b.days >= 1 && b.days <= 365 ? b.days : null;
  if (typeof b.name !== "string" || b.name.trim().length < 2 || b.name.length > 60 || !perms || perms.length === 0 || days === null) return reply({ error: "bad_request" }, 400);
  const r = await apiPost("/v1/api-tokens", JSON.stringify({ name: b.name.trim(), permissions: perms, days }), { "content-type": "application/json" });
  if (r.status === 201) { const j = r.json as { id?: string; name?: string; prefix?: string; token?: string; expires_at?: string }; return reply({ ok: true, id: j.id, name: j.name, prefix: j.prefix, token: j.token, expires_at: j.expires_at }, 201); }
  return teamFailure(r.status, r.json);
}

export const dynamic = "force-dynamic";
