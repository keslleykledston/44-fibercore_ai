import { cookies } from "next/headers";
import { reply, readFields } from "@/lib/mfa-bff";
import { REFRESH_COOKIE, TOKEN_COOKIE, cookieOpts, getSession } from "@/lib/session";

const API = process.env.API_INTERNAL_URL ?? "http://api-core:8000";

/**
 * "MFA recente" (ADR-0031): o usuário digita o código de novo; a API grava a prova na sessão e devolve um access token que a carrega.
 * O refresh token e o access token nunca saem do servidor: a rota só troca o cookie HttpOnly do access token.
 */
export async function POST(req: Request) {
  const f = await readFields(req, [{ name: "code", min: 6, max: 32 }]);
  if (f instanceof Response) return f;
  const { token } = await getSession();
  const jar = await cookies();
  const refresh = jar.get(REFRESH_COOKIE)?.value;
  if (!token || !refresh) return reply({ error: "session" }, 401);
  const res = await fetch(`${API}/v1/auth/mfa/step-up`, {
    method: "POST", cache: "no-store",
    headers: { "content-type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ refresh_token: refresh, code: f.code }),
  });
  let json: { access_token?: string; expires_in?: number; detail?: string } | null = null;
  try { json = await res.json(); } catch { /* sem corpo */ }
  if (res.status === 200 && json?.access_token) {
    jar.set(TOKEN_COOKIE, json.access_token, cookieOpts(json.expires_in ?? 900));
    return reply({ ok: true });
  }
  if (res.status === 409) return reply({ error: "not_enrolled" }, 409);
  if (res.status === 429) return reply({ error: "throttled" }, 429);
  if (res.status === 401) return reply({ error: json?.detail === "invalid credentials" ? "invalid" : "session" }, 401);
  return reply({ error: "failed" }, 502);
}

export const dynamic = "force-dynamic";
