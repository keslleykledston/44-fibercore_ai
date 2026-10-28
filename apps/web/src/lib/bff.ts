import { NextResponse } from "next/server";

export function back(req: Request, to: string) {
  const base = req.headers.get("x-forwarded-host") ? `${req.headers.get("x-forwarded-proto") ?? "https"}://${req.headers.get("x-forwarded-host")}` : new URL(req.url).origin;
  return NextResponse.redirect(new URL(to, base), 303);
}
