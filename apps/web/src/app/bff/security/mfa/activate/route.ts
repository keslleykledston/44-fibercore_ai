import { failure, forward, readFields, reply } from "@/lib/mfa-bff";

export async function POST(req: Request) {
  const f = await readFields(req, [{ name: "code", min: 6, max: 8 }]);
  if (f instanceof Response) return f;
  const r = await forward("/v1/auth/mfa/activate", { code: f.code });
  const j = r.json as { recovery_codes?: string[] } | null;
  if (r.status !== 200 || !Array.isArray(j?.recovery_codes)) return failure(r.status, r.json);
  return reply({ recovery_codes: j.recovery_codes }); // mostrados uma única vez; a API guarda só o hash
}
