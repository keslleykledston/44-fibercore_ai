import { NextResponse } from "next/server";
import { sameOrigin } from "@/lib/csrf";
import { field, orgAction } from "@/lib/orgAction";

/** Renomear a organização (ADR-0047 D1), sem JavaScript. */
export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }) {
  if (!sameOrigin(req)) return NextResponse.json({ detail: "forbidden" }, { status: 403 });
  const { id } = await ctx.params;
  return orgAction(req, id, "/rename", "POST", { name: field((await req.formData()).get("name"), 200) }, "renomeada");
}

export const dynamic = "force-dynamic";
