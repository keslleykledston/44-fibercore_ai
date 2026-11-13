import { NextResponse } from "next/server";
import { sameOrigin } from "@/lib/csrf";
import { field, orgAction } from "@/lib/orgAction";

/** Suspender ou reativar (ADR-0047 D1), sem JavaScript. O motivo é obrigatório (3 a 200 caracteres; o servidor confere). */
export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }) {
  if (!sameOrigin(req)) return NextResponse.json({ detail: "forbidden" }, { status: 403 });
  const { id } = await ctx.params;
  const f = await req.formData();
  const status = field(f.get("status"), 12);
  return orgAction(req, id, "/status", "POST", { status, reason: field(f.get("reason"), 400) }, status === "suspended" ? "suspensa" : "reativada");
}

export const dynamic = "force-dynamic";
