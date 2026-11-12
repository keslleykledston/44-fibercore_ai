import { NextResponse } from "next/server";
import { apiPost } from "@/lib/api";
import { back } from "@/lib/bff";
import { sameOrigin } from "@/lib/csrf";
import { flashFor, LABEL_MAX, nameProblem, UUID } from "@/lib/acs";

const s = (v: FormDataEntryValue | null, max: number) => String(v ?? "").trim().slice(0, max);

/** Renomeia / muda o rótulo, ativa ou desativa um ACS (ADR-0046 D2). O tipo e o Edge não mudam (a API os recusa). */
export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  if (!sameOrigin(req)) return NextResponse.json({ detail: "forbidden" }, { status: 403 });
  const { id } = await params;
  if (!UUID.test(id)) return NextResponse.json({ detail: "not found" }, { status: 404 });
  const f = await req.formData();
  const acao = s(f.get("acao"), 12);
  let body: Record<string, unknown>;
  let ok: string;
  if (acao === "ativar" || acao === "desativar") {
    body = { enabled: acao === "ativar" };
    ok = acao === "ativar" ? "ativado" : "desativado";
  } else if (acao === "salvar") {
    const name = s(f.get("name"), 80), label = s(f.get("label"), LABEL_MAX + 1);
    if (nameProblem(name) || label.length > LABEL_MAX) return back(req, "/rede/acs?erro=invalido");
    body = { name, label: label || null };   // rótulo vazio limpa
    ok = "atualizado";
  } else {
    return back(req, "/rede/acs?erro=invalido");
  }
  const r = await apiPost(`/v1/acs/${id}`, JSON.stringify(body), { "Content-Type": "application/json" }, "PATCH");
  if (r.status === 200) return back(req, `/rede/acs?ok=${ok}`);
  return back(req, `/rede/acs?erro=${flashFor(r.status, (r.json as { detail?: unknown } | null)?.detail)}`);
}
