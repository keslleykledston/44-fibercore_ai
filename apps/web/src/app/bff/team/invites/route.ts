import { apiPost } from "@/lib/api";
import { sameOrigin } from "@/lib/csrf";
import { reply } from "@/lib/mfa-bff";
import { ROLE, teamFailure } from "@/lib/team-bff";

/** Convida uma pessoa. A resposta traz o token UMA vez (a tela monta o link); nada é enviado por e-mail. */
export async function POST(req: Request) {
  if (!sameOrigin(req)) return reply({ error: "forbidden" }, 403);
  const raw = await req.text();
  if (raw.length > 1024) return reply({ error: "bad_request" }, 413);
  let b: { email?: unknown; name?: unknown; role?: unknown };
  try { b = JSON.parse(raw); } catch { return reply({ error: "bad_request" }, 400); }
  if (typeof b.email !== "string" || b.email.length < 3 || b.email.length > 254 || typeof b.role !== "string" || !ROLE.test(b.role)) return reply({ error: "bad_request" }, 400);
  const name = typeof b.name === "string" && b.name.trim() ? b.name.trim().slice(0, 100) : undefined;
  const r = await apiPost("/v1/team/invites", JSON.stringify({ email: b.email.trim(), name, role: b.role }), { "content-type": "application/json" });
  if (r.status === 201) {
    const j = r.json as { id?: string; token?: string; expires_at?: string; role_label?: string; email?: string };
    return reply({ ok: true, id: j.id, token: j.token, expires_at: j.expires_at, role_label: j.role_label, email: j.email }, 201);
  }
  return teamFailure(r.status, r.json);
}

export const dynamic = "force-dynamic";
