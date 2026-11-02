import { NextResponse } from "next/server";
import { apiPost } from "@/lib/api";
import { back } from "@/lib/bff";
import { sameOrigin } from "@/lib/csrf";
import { UUID } from "@/lib/fleet";

const s = (v: FormDataEntryValue | null, max: number) => String(v ?? "").trim().slice(0, max);

/** Cadastra uma OLT (nuvem apenas: nada é enviado à OLT). O campo da credencial é um NOME, nunca um segredo; o valor não é repetido em nenhuma mensagem. */
export async function POST(req: Request) {
  if (!sameOrigin(req)) return NextResponse.json({ detail: "forbidden" }, { status: 403 });
  const f = await req.formData();
  const edge = s(f.get("edge_id"), 40), pop = s(f.get("pop_id"), 40);
  if (!UUID.test(edge) || (pop && !UUID.test(pop))) return back(req, "/rede/frota?erro=invalido");
  const body: Record<string, unknown> = { name: s(f.get("name"), 60), edge_id: edge, vendor: s(f.get("vendor"), 20) };
  if (pop) body.pop_id = pop;
  const cred = s(f.get("credential_ref"), 64), label = s(f.get("label"), 80);
  if (cred) body.credential_ref = cred;
  if (label) body.label = label;
  const r = await apiPost("/v1/fleet/olts", JSON.stringify(body), { "Content-Type": "application/json" });
  if (r.status === 201) return back(req, "/rede/frota?ok=olt");
  const why = r.status === 403 ? (JSON.stringify(r.json ?? {}).includes("feature_disabled") ? "desligado" : "permissao") : r.status === 409 ? "nome" : r.status === 422 ? "invalido"
    : r.status === 404 ? (JSON.stringify(r.json ?? {}).includes("pop") ? "popinexistente" : "edge") : "falha";
  return back(req, `/rede/frota?erro=${why}`);
}
