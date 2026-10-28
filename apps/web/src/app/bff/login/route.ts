import { NextResponse } from "next/server";
import { apiLogin } from "@/lib/api";
import { sameOrigin } from "@/lib/csrf";
import { TOKEN_COOKIE, WS_COOKIE, cookieOpts } from "@/lib/session";

export async function POST(req: Request) {
  if (!sameOrigin(req)) return NextResponse.json({ detail: "forbidden" }, { status: 403 });
  const form = await req.formData();
  const email = String(form.get("email") ?? "");
  const password = String(form.get("password") ?? "");
  const { token, status } = email && password ? await apiLogin(email, password) : { token: null, status: 401 };
  const base = req.headers.get("x-forwarded-host") ? `${req.headers.get("x-forwarded-proto") ?? "https"}://${req.headers.get("x-forwarded-host")}` : new URL(req.url).origin;
  if (!token) return NextResponse.redirect(new URL(status === 429 ? "/login?erro=429" : "/login?erro=1", base), 303);
  const res = NextResponse.redirect(new URL("/", base), 303);
  res.cookies.set(TOKEN_COOKIE, token, cookieOpts(15 * 60)); // mesmo TTL do token da API
  res.cookies.delete(WS_COOKIE);
  return res;
}
