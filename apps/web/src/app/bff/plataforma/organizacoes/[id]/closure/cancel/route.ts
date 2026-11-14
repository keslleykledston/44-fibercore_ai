import { NextResponse } from "next/server";
import { sameOrigin } from "@/lib/csrf";
import { field, orgAction } from "@/lib/orgAction";

/** Cancelar o pedido de encerramento (ADR-0050 D1), sem JavaScript. */
export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }) {
  if (!sameOrigin(req)) return NextResponse.json({ detail: "forbidden" }, { status: 403 });
  const { id } = await ctx.params;
  const f = await req.formData();
  return orgAction(req, id, "/closure/cancel", "POST", { reason: field(f.get("reason"), 400) }, "encerramentocancelado");
}

export const dynamic = "force-dynamic";
