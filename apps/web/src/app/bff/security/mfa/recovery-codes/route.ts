import { failure, forward, readFields, reply } from "@/lib/mfa-bff";

export async function POST(req: Request) {
  const f = await readFields(req, [{ name: "password", min: 1, max: 256 }, { name: "code", min: 6, max: 32 }]);
  if (f instanceof Response) return f;
  const r = await forward("/v1/auth/mfa/recovery-codes", { password: f.password, code: f.code });
  if (r.status !== 200) return failure(r.status, r.json);
  const codes = (r.json as { recovery_codes?: unknown } | null)?.recovery_codes;
  return Array.isArray(codes) ? reply({ recovery_codes: codes }) : reply({ error: "failed" }, 502);  // mostrados uma única vez; no-store
}
