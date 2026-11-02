import { NextResponse } from "next/server";
import { apiPost } from "@/lib/api";
import { back } from "@/lib/bff";
import { sameOrigin } from "@/lib/csrf";
import { UUID } from "@/lib/profiles";

/** Simulação (dry-run): zero escrita, resultado guardado e reproduzível. Não existe "executar" nesta entrega. */
export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  if (!sameOrigin(req)) return NextResponse.json({ detail: "forbidden" }, { status: 403 });
  const { id } = await params;
  if (!UUID.test(id)) return NextResponse.json({ detail: "not found" }, { status: 404 });
  const r = await apiPost(`/v1/profile-drafts/${id}/dry-run`, JSON.stringify({}), { "Content-Type": "application/json" });
  const run = (r.json as { run_id?: string } | null)?.run_id;
  if (r.status === 201 && run && UUID.test(run)) return back(req, `/rede/perfis/${id}?run=${run}`);
  return back(req, `/rede/perfis/${id}?erro=${r.status === 403 ? "permissao" : r.status === 422 ? "semalvo" : "falha"}`);
}
