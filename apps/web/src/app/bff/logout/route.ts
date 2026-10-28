import { NextResponse } from "next/server";
import { sameOrigin } from "@/lib/csrf";
import { TOKEN_COOKIE, WS_COOKIE } from "@/lib/session";

export async function POST(req: Request) {
  if (!sameOrigin(req)) return NextResponse.json({ detail: "forbidden" }, { status: 403 });
  const base = req.headers.get("x-forwarded-host") ? `${req.headers.get("x-forwarded-proto") ?? "https"}://${req.headers.get("x-forwarded-host")}` : new URL(req.url).origin;
  const res = NextResponse.redirect(new URL("/login", base), 303);
  res.cookies.delete(TOKEN_COOKIE);
  res.cookies.delete(WS_COOKIE);
  return res;
}
