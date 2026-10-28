import { NextResponse } from "next/server";
import { sameOrigin } from "@/lib/csrf";
import { WS_COOKIE, cookieOpts } from "@/lib/session";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export async function POST(req: Request) {
  if (!sameOrigin(req)) return NextResponse.json({ detail: "forbidden" }, { status: 403 });
  const ws = String((await req.formData()).get("workspace") ?? "");
  const base = req.headers.get("x-forwarded-host") ? `${req.headers.get("x-forwarded-proto") ?? "https"}://${req.headers.get("x-forwarded-host")}` : new URL(req.url).origin;
  if (!UUID.test(ws)) return NextResponse.redirect(new URL("/", base), 303);
  const res = NextResponse.redirect(new URL("/", base), 303);
  res.cookies.set(WS_COOKIE, ws, cookieOpts(15 * 60)); // o servidor valida a membership a cada chamada (404 se não for membro)
  return res;
}
