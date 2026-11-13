import { NextResponse } from "next/server";
import { back } from "@/lib/bff";
import { sameOrigin } from "@/lib/csrf";
import { field, orgAction } from "@/lib/orgAction";
import { FEATURE_FORMAT, FEATURE_STATES, UUID_FORMAT } from "@/lib/platform";

/** Ligar, desligar ou voltar ao padrão um recurso da organização (ADR-0047 D2), sem JavaScript. O nome só segue se tiver o formato de recurso; o catálogo e as regras "só o dono" são da API. */
export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }) {
  if (!sameOrigin(req)) return NextResponse.json({ detail: "forbidden" }, { status: 403 });
  const { id } = await ctx.params;
  const f = await req.formData();
  const feature = field(f.get("feature"), 64), state = field(f.get("state"), 10);
  if (!UUID_FORMAT.test(id) || !FEATURE_FORMAT.test(feature) || !(FEATURE_STATES as readonly string[]).includes(state)) return back(req, UUID_FORMAT.test(id) ? `/plataforma/organizacoes/${id}?erro=flag` : "/plataforma/organizacoes?erro=naoencontrada");
  return orgAction(req, id, `/features/${feature}`, "PUT", { state, reason: field(f.get("reason"), 400) }, "flagok");
}

export const dynamic = "force-dynamic";
