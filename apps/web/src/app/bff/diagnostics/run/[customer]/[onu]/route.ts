import { NextResponse } from "next/server";
import { apiPost } from "@/lib/api";
import { back } from "@/lib/bff";
import { sameOrigin } from "@/lib/csrf";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Executa a regra R-D001 (somente leitura) para a PON da ONU e volta para a tela com o resultado. */
export async function POST(req: Request, { params }: { params: Promise<{ customer: string; onu: string }> }) {
  if (!sameOrigin(req)) return NextResponse.json({ detail: "forbidden" }, { status: 403 });
  const { customer, onu } = await params;
  if (!UUID.test(customer) || !UUID.test(onu)) return NextResponse.json({ detail: "not found" }, { status: 404 });
  const r = await apiPost("/v1/diagnostics/runs", JSON.stringify({ rule_id: "R-D001", onu_id: onu }), { "content-type": "application/json" });
  const runId = (r.json as { run_id?: string } | null)?.run_id;
  const ok = r.status === 201 && typeof runId === "string" && UUID.test(runId);
  return back(req, `/assinantes/diagnostico/${customer}?onu=${onu}&${ok ? `run=${runId}` : `erro=${r.status}`}`);
}
