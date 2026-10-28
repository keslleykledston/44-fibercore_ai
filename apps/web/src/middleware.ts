import { NextResponse, type NextRequest } from "next/server";
import { publicBase } from "@/lib/bff";

// Renova o access token (cookie de 15 min) com o refresh token rotativo. Só navegações de página: prefetch não consome o refresh,
// porque a API trata reutilização de um refresh já consumido como vazamento e revoga a sessão inteira.
const API = process.env.API_INTERNAL_URL ?? "http://api-core:8000";
const insecure = process.env.FIBERCORE_INSECURE_COOKIES === "1";
const opts = (maxAge: number) => ({ httpOnly: true, secure: !insecure, sameSite: "lax" as const, path: "/", maxAge });

export async function middleware(req: NextRequest) {
  const refresh = req.cookies.get("fc_refresh")?.value;
  if (req.cookies.get("fc_token")?.value || !refresh) return NextResponse.next();
  if (req.headers.get("next-router-prefetch") || req.headers.get("purpose") === "prefetch") return NextResponse.next();
  let body: { access_token?: string; refresh_token?: string; expires_in?: number } | null = null;
  try {
    const r = await fetch(`${API}/v1/auth/refresh`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ refresh_token: refresh }), cache: "no-store" });
    if (r.ok) body = await r.json();
    else if (r.status !== 401 && r.status !== 422) return NextResponse.next(); // API indisponível: não derruba a sessão
  } catch { return NextResponse.next(); }
  if (!body?.access_token || !body.refresh_token) {
    const res = NextResponse.redirect(new URL("/login", publicBase(req)), 303);
    for (const n of ["fc_token", "fc_refresh", "fc_ws"]) res.cookies.delete(n);
    return res;
  }
  req.cookies.set("fc_token", body.access_token); // visível para a renderização desta mesma requisição
  req.cookies.set("fc_refresh", body.refresh_token);
  const res = NextResponse.next({ request: { headers: req.headers } });
  res.cookies.set("fc_token", body.access_token, opts(body.expires_in ?? 900));
  res.cookies.set("fc_refresh", body.refresh_token, opts(8 * 3600));
  return res;
}

export const config = { matcher: ["/((?!_next/|bff/|login|ajuda-assets/|favicon).*)"] };
