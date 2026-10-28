import { NextResponse } from "next/server";

/** Origem pública (atrás do proxy de borda). */
export function publicBase(req: Request): string {
  return req.headers.get("x-forwarded-host") ? `${req.headers.get("x-forwarded-proto") ?? "https"}://${req.headers.get("x-forwarded-host")}` : new URL(req.url).origin;
}

export function clientIp(req: Request): string | undefined {
  return (req.headers.get("x-forwarded-for") ?? "").split(",")[0].trim().slice(0, 64) || undefined;
}

export function back(req: Request, to: string) {
  return NextResponse.redirect(new URL(to, publicBase(req)), 303);
}
