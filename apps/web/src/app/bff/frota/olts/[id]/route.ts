import { NextResponse } from "next/server";
import { apiPost } from "@/lib/api";
import { back } from "@/lib/bff";
import { sameOrigin } from "@/lib/csrf";
import { UUID } from "@/lib/fleet";

const s = (v: FormDataEntryValue | null, max: number) => String(v ?? "").trim().slice(0, max);

/** Edita o POP, o rótulo e o NOME da credencial de uma OLT. POP e rótulo vazios limpam; a credencial só muda por substituição ou remoção explícita. Nada é enviado à OLT. */
export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  if (!sameOrigin(req)) return NextResponse.json({ detail: "forbidden" }, { status: 403 });
  const { id } = await params;
  if (!UUID.test(id)) return NextResponse.json({ detail: "not found" }, { status: 404 });
  const f = await req.formData();
  const pop = s(f.get("pop_id"), 40);
  if (pop && !UUID.test(pop)) return back(req, `/rede/frota/${id}?erro=invalido`);
  const body: Record<string, unknown> = { pop_id: pop || null, label: s(f.get("label"), 80) || null };
  // o nome da credencial nunca volta da API: o campo vem vazio e só muda quando a pessoa SUBSTITUI (digitando) ou REMOVE (caixa); campo vazio sem a caixa não toca na credencial
  const cred = s(f.get("credential_ref"), 64);
  if (f.get("remover_credencial") === "1") body.credential_ref = null;
  else if (cred) body.credential_ref = cred;
  const r = await apiPost(`/v1/fleet/olts/${id}`, JSON.stringify(body), { "Content-Type": "application/json" }, "PATCH");
  if (r.status === 200) return back(req, `/rede/frota/${id}?ok=oltatualizada`);
  return back(req, `/rede/frota/${id}?erro=${r.status === 403 ? "permissao" : r.status === 422 ? "invalido" : r.status === 404 ? "popinexistente" : "falha"}`);
}
