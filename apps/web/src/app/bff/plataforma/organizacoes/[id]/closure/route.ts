import { NextResponse } from "next/server";
import { sameOrigin } from "@/lib/csrf";
import { field, orgAction } from "@/lib/orgAction";

/** Pedir o encerramento de uma organização suspensa (ADR-0050 D1), sem JavaScript. A tela NÃO apaga nada: abre uma carência de 7 dias; o dono exporta e apaga no host. */
export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }) {
  if (!sameOrigin(req)) return NextResponse.json({ detail: "forbidden" }, { status: 403 });
  const { id } = await ctx.params;
  const f = await req.formData();
  return orgAction(req, id, "/closure", "POST", { reason: field(f.get("reason"), 400) }, "encerramentopedido");
}

export const dynamic = "force-dynamic";
