import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { back } from "@/lib/bff";
import { sameOrigin } from "@/lib/csrf";
import { stepUpError } from "@/lib/platform";
import { REFRESH_COOKIE, TOKEN_COOKIE, cookieOpts, getSession } from "@/lib/session";

const API = process.env.API_INTERNAL_URL ?? "http://api-core:8000";

/** O mesmo passo do "MFA recente" de `/bff/mfa/step-up`, mas para formulário sem JavaScript: devolve um redirecionamento em vez de JSON. O código é redigitado; só o cookie do access token é trocado. */
export async function POST(req: Request) {
  if (!sameOrigin(req)) return NextResponse.json({ detail: "forbidden" }, { status: 403 });
  const code = String((await req.formData()).get("code") ?? "").trim();
  if (code.length < 6 || code.length > 32) return back(req, "/plataforma/organizacoes?erro=codigo");
  const { token } = await getSession();
  const jar = await cookies();
  const refresh = jar.get(REFRESH_COOKIE)?.value;
  if (!token || !refresh) return back(req, "/login");
  const res = await fetch(`${API}/v1/auth/mfa/step-up`, {
    method: "POST", cache: "no-store",
    headers: { "content-type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ refresh_token: refresh, code }),
  });
  let json: { access_token?: string; expires_in?: number } | null = null;
  try { json = await res.json(); } catch { /* sem corpo */ }
  if (res.status === 200 && json?.access_token) {
    jar.set(TOKEN_COOKIE, json.access_token, cookieOpts(json.expires_in ?? 900));
    return back(req, "/plataforma/organizacoes?ok=mfaok");
  }
  return back(req, `/plataforma/organizacoes?erro=${stepUpError(res.status)}`);
}

export const dynamic = "force-dynamic";
