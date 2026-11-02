import { NextResponse } from "next/server";
import { apiPost } from "@/lib/api";
import { back } from "@/lib/bff";
import { sameOrigin } from "@/lib/csrf";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Executa uma regra do diagnóstico guiado (somente leitura) para a ONU e volta para a tela com o resultado. `?rule=` só aceita R-D001 (padrão coletivo na PON) ou R-D004 (sessão do roteador com o ACS);
 *  `?keep=` é a execução da OUTRA regra, mantida na volta. */
export async function POST(req: Request, { params }: { params: Promise<{ customer: string; onu: string }> }) {
  if (!sameOrigin(req)) return NextResponse.json({ detail: "forbidden" }, { status: 403 });
  const { customer, onu } = await params;
  if (!UUID.test(customer) || !UUID.test(onu)) return NextResponse.json({ detail: "not found" }, { status: 404 });
  const u = new URL(req.url);
  const rule = u.searchParams.get("rule") === "R-D004" ? "R-D004" : "R-D001";
  const keepRaw = u.searchParams.get("keep");
  const keep = keepRaw && UUID.test(keepRaw) ? keepRaw : null;
  const r = await apiPost("/v1/diagnostics/runs", JSON.stringify({ rule_id: rule, onu_id: onu }), { "content-type": "application/json" });
  const runId = (r.json as { run_id?: string } | null)?.run_id;
  const ok = r.status === 201 && typeof runId === "string" && UUID.test(runId);
  const mine = rule === "R-D004" ? "run4" : "run", theirs = rule === "R-D004" ? "run" : "run4";
  const qs = `onu=${onu}${ok ? `&${mine}=${runId}` : `&erro=${r.status}`}${keep ? `&${theirs}=${keep}` : ""}${rule === "R-D004" ? "&passo=6" : ""}`;
  return back(req, `/assinantes/diagnostico/${customer}?${qs}`);
}
