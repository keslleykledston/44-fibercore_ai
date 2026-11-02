import { NextResponse } from "next/server";
import { apiPost } from "@/lib/api";
import { back } from "@/lib/bff";
import { sameOrigin } from "@/lib/csrf";
import { UUID } from "@/lib/profiles";

const str = (f: FormData, k: string, max: number) => String(f.get(k) ?? "").trim().slice(0, max);

/** Cria um rascunho como CÓPIA de um instantâneo (o instantâneo nunca é alterado). */
export async function POST(req: Request) {
  if (!sameOrigin(req)) return NextResponse.json({ detail: "forbidden" }, { status: 403 });
  const f = await req.formData();
  const snap = str(f, "snapshot", 40), olt = str(f, "olt", 40), name = str(f, "name", 80), reason = str(f, "reason", 300);
  if (!UUID.test(snap) || !UUID.test(olt)) return NextResponse.json({ detail: "not found" }, { status: 404 });
  if (!name || !reason) return back(req, `/rede/perfis?olt=${olt}&erro=invalido`);
  const r = await apiPost("/v1/profile-drafts", JSON.stringify({ name, reason, source_snapshot_id: snap, target_olt_ids: [olt] }), { "Content-Type": "application/json" });
  const id = (r.json as { id?: string } | null)?.id;
  if (r.status === 201 && id && UUID.test(id)) return back(req, `/rede/perfis/${id}`);
  return back(req, `/rede/perfis?olt=${olt}&erro=${r.status === 403 ? "permissao" : r.status === 422 ? "invalido" : "falha"}`);
}
