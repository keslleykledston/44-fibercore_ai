import { NextResponse } from "next/server";
import { apiPost } from "@/lib/api";
import { back } from "@/lib/bff";
import { sameOrigin } from "@/lib/csrf";
import { UUID } from "@/lib/profiles";

/** Publica a revisão IMUTÁVEL do rascunho na versão exata que a pessoa leu (If-Match). Quem aprova não é quem preparou (maker-checker); o rascunho precisa ter sido simulado nessa versão. Nada vai à OLT. */
export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  if (!sameOrigin(req)) return NextResponse.json({ detail: "forbidden" }, { status: 403 });
  const { id } = await params;
  if (!UUID.test(id)) return NextResponse.json({ detail: "not found" }, { status: 404 });
  const f = await req.formData();
  const to = (q: string) => `/rede/perfis/${id}?${q}`;
  const version = String(f.get("version") ?? "").trim().slice(0, 10);
  const changelog = String(f.get("changelog") ?? "").trim().slice(0, 2000);
  if (!/^[0-9]{1,9}$/.test(version) || changelog.length < 3) return back(req, to("erro=changelog"));
  const r = await apiPost(`/v1/profile-drafts/${id}/publish`, JSON.stringify({ changelog }), { "Content-Type": "application/json", "If-Match": `"${version}"` });
  if (r.status === 201 || r.status === 200) return back(req, to("ok=publicado"));
  const text = JSON.stringify(r.json ?? {});
  if (r.status === 403) return back(req, to(`erro=${text.includes("maker_checker") ? "maker" : "permissao"}`));
  return back(req, to(`erro=${r.status === 409 ? "semsimulacao" : r.status === 412 ? "versao" : r.status === 422 ? "invalido" : "falha"}`));
}
