import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { publicBase } from "@/lib/bff";
import { sameOrigin } from "@/lib/csrf";
import { REFRESH_COOKIE, clearSessionCookies } from "@/lib/session";

const API = process.env.API_INTERNAL_URL ?? "http://api-core:8000";

export async function POST(req: Request) {
  if (!sameOrigin(req)) return NextResponse.json({ detail: "forbidden" }, { status: 403 });
  const base = publicBase(req);
  const refresh = (await cookies()).get(REFRESH_COOKIE)?.value;
  if (refresh) { // revoga a família no servidor; falha de rede não impede o logout local
    try { await fetch(`${API}/v1/auth/logout`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ refresh_token: refresh }), cache: "no-store" }); } catch { /* segue */ }
  }
  const res = NextResponse.redirect(new URL("/login", base), 303);
  clearSessionCookies(res.cookies);
  return res;
}
