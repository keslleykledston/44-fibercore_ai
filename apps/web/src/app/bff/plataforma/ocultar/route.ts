import { NextResponse } from "next/server";
import { back } from "@/lib/bff";
import { sameOrigin } from "@/lib/csrf";
import { FLASH_COOKIE, FLASH_PATH } from "@/lib/platform";

/** Apaga o cookie do link do convite (a tela o mostra uma vez; isto o tira antes dos 2 minutos). */
export async function POST(req: Request) {
  if (!sameOrigin(req)) return NextResponse.json({ detail: "forbidden" }, { status: 403 });
  const res = back(req, "/plataforma/organizacoes?ok=oculto");
  res.cookies.set(FLASH_COOKIE, "", { path: FLASH_PATH, maxAge: 0 });
  return res;
}

export const dynamic = "force-dynamic";
