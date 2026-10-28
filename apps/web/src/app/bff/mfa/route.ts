import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { apiMfaVerify } from "@/lib/api";
import { clientIp, publicBase } from "@/lib/bff";
import { sameOrigin } from "@/lib/csrf";
import { MFA_COOKIE, WS_COOKIE, setSessionCookies } from "@/lib/session";

export async function POST(req: Request) {
  if (!sameOrigin(req)) return NextResponse.json({ detail: "forbidden" }, { status: 403 });
  const base = publicBase(req);
  const mfaToken = (await cookies()).get(MFA_COOKIE)?.value ?? "";
  const code = String((await req.formData()).get("code") ?? "").trim();
  if (!mfaToken) return NextResponse.redirect(new URL("/login", base), 303);
  const r = code ? await apiMfaVerify(mfaToken, code, clientIp(req)) : ({ kind: "error", status: 401 } as const);
  if (r.kind !== "session") {
    const res = NextResponse.redirect(new URL(r.kind === "error" && r.status === 429 ? "/login/mfa?erro=429" : r.kind === "error" && r.status === 401 ? "/login/mfa?erro=1" : "/login", base), 303);
    if (r.kind === "error" && r.status !== 401 && r.status !== 429) res.cookies.delete(MFA_COOKIE);
    return res;
  }
  const res = NextResponse.redirect(new URL("/", base), 303);
  setSessionCookies(res.cookies, r.access, r.refresh, r.expiresIn);
  res.cookies.delete(WS_COOKIE);
  return res;
}
