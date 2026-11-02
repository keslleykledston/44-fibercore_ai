import { NextResponse } from "next/server";
import { apiPost } from "@/lib/api";
import { back } from "@/lib/bff";
import { sameOrigin } from "@/lib/csrf";
import { parseLines } from "@/lib/discovery";
import { UUID } from "@/lib/profiles";

/** Registra avistamentos à mão (origem SEMPRE `manual_import`, nunca autoritativa). Nada é enviado à OLT. */
export async function POST(req: Request) {
  if (!sameOrigin(req)) return NextResponse.json({ detail: "forbidden" }, { status: 403 });
  const f = await req.formData();
  const olt = String(f.get("olt") ?? "").trim().slice(0, 40);
  if (!UUID.test(olt)) return NextResponse.json({ detail: "not found" }, { status: 404 });
  const to = (q: string) => `/rede/pendentes?olt=${olt}&${q}`;
  const items = parseLines(String(f.get("linhas") ?? "").slice(0, 4000), new Date().toISOString());
  if (!items) return back(req, to("erro=invalido"));
  const r = await apiPost(`/v1/olts/${olt}/onus/unregistered/import`, JSON.stringify({ source: "manual_import", items }), { "Content-Type": "application/json" });
  if (r.status === 201) return back(req, to("ok=registrado"));
  return back(req, to(`erro=${r.status === 403 ? "permissao" : r.status === 422 ? "invalido" : "falha"}`));
}
