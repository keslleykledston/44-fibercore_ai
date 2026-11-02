import { NextResponse } from "next/server";
import { apiPost } from "@/lib/api";
import { back } from "@/lib/bff";
import { sameOrigin } from "@/lib/csrf";
import { UUID } from "@/lib/profiles";

/** Transforma a última leitura da lista de ONUs detectadas (já feita pelo Edge e guardada) em avistamentos AUTORITATIVOS. Não pergunta nada à OLT e não autoriza nada. */
export async function POST(req: Request) {
  if (!sameOrigin(req)) return NextResponse.json({ detail: "forbidden" }, { status: 403 });
  const f = await req.formData();
  const olt = String(f.get("olt") ?? "").trim().slice(0, 40);
  if (!UUID.test(olt)) return NextResponse.json({ detail: "not found" }, { status: 404 });
  const to = (q: string) => `/rede/pendentes?olt=${olt}&${q}`;
  const r = await apiPost(`/v1/olts/${olt}/onus/unregistered/sync`, JSON.stringify({}), { "Content-Type": "application/json" });
  if (r.status === 200) {
    const j = r.json as { created?: number; updated?: number; unchanged?: number } | null;
    const n = (v: unknown) => Math.min(999, Math.max(0, Math.trunc(Number(v ?? 0)) || 0));
    return back(req, to(`ok=sincronizado&n=${n(j?.created)}&u=${n(j?.updated)}&s=${n(j?.unchanged)}`));
  }
  if (r.status === 403) return back(req, to("erro=permissao"));
  if (r.status === 409) {
    const text = JSON.stringify(r.json ?? {});
    return back(req, to(`erro=${text.includes("no_read") ? "semleitura" : text.includes("read_too_old") ? "leituraantiga" : "leituraruim"}`));
  }
  return back(req, to("erro=falha"));
}
