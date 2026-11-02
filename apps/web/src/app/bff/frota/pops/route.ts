import { NextResponse } from "next/server";
import { apiPost } from "@/lib/api";
import { back } from "@/lib/bff";
import { sameOrigin } from "@/lib/csrf";

const s = (v: FormDataEntryValue | null, max: number) => String(v ?? "").trim().slice(0, max);

export async function POST(req: Request) {
  if (!sameOrigin(req)) return NextResponse.json({ detail: "forbidden" }, { status: 403 });
  const f = await req.formData();
  const body: Record<string, unknown> = { name: s(f.get("name"), 60) };
  const code = s(f.get("code"), 24), note = s(f.get("note"), 200);
  if (code) body.code = code;
  if (note) body.note = note;
  const r = await apiPost("/v1/pops", JSON.stringify(body), { "Content-Type": "application/json" });
  if (r.status === 201) return back(req, "/rede/frota?ok=pop");
  return back(req, `/rede/frota?erro=${r.status === 403 ? "permissao" : r.status === 409 ? "nome" : r.status === 422 ? "invalido" : "falha"}`);
}
