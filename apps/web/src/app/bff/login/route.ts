import { NextResponse } from "next/server";
import { apiLogin } from "@/lib/api";
import { clientIp, publicBase } from "@/lib/bff";
import { sameOrigin } from "@/lib/csrf";
import { MFA_COOKIE, WS_COOKIE, cookieOpts, setSessionCookies } from "@/lib/session";

export async function POST(req: Request) {
  if (!sameOrigin(req)) return NextResponse.json({ detail: "forbidden" }, { status: 403 });
  const form = await req.formData();
  const email = String(form.get("email") ?? "");
  const password = String(form.get("password") ?? "");
  const r = email && password ? await apiLogin(email, password, clientIp(req)) : ({ kind: "error", status: 401 } as const);
  const base = publicBase(req);
  if (r.kind === "error") return NextResponse.redirect(new URL(r.status === 429 ? "/login?erro=429" : "/login?erro=1", base), 303);
  if (r.kind === "mfa") {
    const res = NextResponse.redirect(new URL("/login/mfa", base), 303);
    res.cookies.set(MFA_COOKIE, r.mfaToken, cookieOpts(5 * 60));
    return res;
  }
  const res = NextResponse.redirect(new URL("/", base), 303);
  setSessionCookies(res.cookies, r.access, r.refresh, r.expiresIn);
  res.cookies.delete(WS_COOKIE);
  return res;
}
