import { failure, forward, readFields, reply } from "@/lib/mfa-bff";

export async function POST(req: Request) {
  const f = await readFields(req, [{ name: "password", min: 1, max: 256 }, { name: "code", min: 6, max: 32 }]);
  if (f instanceof Response) return f;
  const r = await forward("/v1/auth/mfa/disable", { password: f.password, code: f.code });
  return r.status === 204 ? reply({ ok: true }) : failure(r.status, r.json);
}
