import { NextResponse } from "next/server";
import { apiPost } from "@/lib/api";
import { back } from "@/lib/bff";
import { sameOrigin } from "@/lib/csrf";

const MAX = 2 * 1024 * 1024;

export async function POST(req: Request) {
  if (!sameOrigin(req)) return NextResponse.json({ detail: "forbidden" }, { status: 403 });
  // Limite ANTES de parsear o multipart: Content-Length obrigatório e <= arquivo máximo + margem de envelope.
  const declared = req.headers.get("content-length");
  if (!declared || !/^\d+$/.test(declared)) return NextResponse.json({ detail: "length required" }, { status: 411 });
  if (Number(declared) > MAX + 64 * 1024) return back(req, "/assinantes?erro=arquivo");
  const form = await req.formData();
  const file = form.get("file");
  const source = String(form.get("source") ?? "csv-manual");
  if (!(file instanceof File) || file.size === 0 || file.size > MAX) return back(req, "/assinantes?erro=arquivo");
  const buf = await file.arrayBuffer();
  const r = await apiPost(`/v1/erp/import-csv?source=${encodeURIComponent(source)}`, buf, { "content-type": "text/csv", "content-length": String(buf.byteLength) });
  if (r.status !== 200) return back(req, `/assinantes?erro=${r.status}`);
  const j = r.json as { accepted: number; rejected_count: number; suggestions: number; conflicts: number };
  // Só contagens trafegam na URL: nunca valores do CSV (podem ser dados pessoais).
  return back(req, `/assinantes?ok=import&a=${j.accepted}&r=${j.rejected_count}&s=${j.suggestions}&c=${j.conflicts}`);
}
