import { NextResponse } from "next/server";
import { back } from "@/lib/bff";
import { sameOrigin } from "@/lib/csrf";
import { field, orgAction } from "@/lib/orgAction";
import { limitsPayload, UUID_FORMAT } from "@/lib/platform";

/** Limites técnicos da organização (ADR-0047 D3), sem JavaScript. Campo vazio = não mexe; "Padrão" = volta ao padrão do código. Faixas e chaves são validadas de novo pela API e pelo banco. */
export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }) {
  if (!sameOrigin(req)) return NextResponse.json({ detail: "forbidden" }, { status: 403 });
  const { id } = await ctx.params;
  const f = await req.formData();
  const built = limitsPayload((n) => field(f.get(n), 12));
  if (!UUID_FORMAT.test(id) || "erro" in built) return back(req, UUID_FORMAT.test(id) && "erro" in built ? `/plataforma/organizacoes/${id}?erro=${built.erro}` : "/plataforma/organizacoes?erro=naoencontrada");
  return orgAction(req, id, "/limits", "PUT", { limits: built.limits, reason: field(f.get("reason"), 400) }, "limitesok");
}

export const dynamic = "force-dynamic";
