import { apiPost } from "@/lib/api";
import { reply } from "@/lib/mfa-bff";
import { isResponse, readJson, strList, teamFailure } from "@/lib/team-bff";

/** Política de MFA da organização (ADR-0049 D1): só APERTA o piso do ambiente. PUT {mfa_required_roles}. */
export async function PUT(req: Request) {
  const b = await readJson(req);
  if (isResponse(b)) return b;
  const roles = strList(b.mfa_required_roles, 10);
  if (!roles) return reply({ error: "bad_request" }, 400);
  const r = await apiPost("/v1/security-policy", JSON.stringify({ mfa_required_roles: roles }), { "content-type": "application/json" }, "PUT");
  if (r.status === 200) { const j = r.json as { changed?: boolean }; return reply({ ok: true, changed: j.changed === true }); }
  return teamFailure(r.status, r.json);
}

export const dynamic = "force-dynamic";
