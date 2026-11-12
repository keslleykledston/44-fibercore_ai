import { NextResponse } from "next/server";
import { apiPost } from "@/lib/api";
import { back } from "@/lib/bff";
import { sameOrigin } from "@/lib/csrf";
import { flashFor, KIND_LABEL, LABEL_MAX, nameProblem, UUID } from "@/lib/acs";

const s = (v: FormDataEntryValue | null, max: number) => String(v ?? "").trim().slice(0, max);

/** Cadastra o ACS de um Edge (ADR-0046 D2). Só o cadastro: nome, tipo, Edge, rótulo e se já fica ativo. Nunca URL nem senha do ACS (ficam no Edge); o texto digitado não volta em mensagem. */
export async function POST(req: Request) {
  if (!sameOrigin(req)) return NextResponse.json({ detail: "forbidden" }, { status: 403 });
  const f = await req.formData();
  const name = s(f.get("name"), 80), edge = s(f.get("edge_id"), 40), kind = s(f.get("kind"), 32), label = s(f.get("label"), LABEL_MAX + 1);
  if (nameProblem(name) || !UUID.test(edge) || !(kind in KIND_LABEL) || label.length > LABEL_MAX) return back(req, "/rede/acs?erro=invalido");
  const body: Record<string, unknown> = { name, edge_id: edge, kind, enabled: f.get("enabled") === "1" };
  if (label) body.label = label;
  const r = await apiPost("/v1/acs", JSON.stringify(body), { "Content-Type": "application/json" });
  if (r.status === 201) return back(req, "/rede/acs?ok=criado");
  return back(req, `/rede/acs?erro=${flashFor(r.status, (r.json as { detail?: unknown } | null)?.detail)}`);
}
