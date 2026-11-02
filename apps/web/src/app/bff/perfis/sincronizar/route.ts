import { NextResponse } from "next/server";
import { apiPost } from "@/lib/api";
import { back } from "@/lib/bff";
import { sameOrigin } from "@/lib/csrf";
import { UUID } from "@/lib/profiles";

/** Transforma a última leitura (já feita pelo Edge e guardada) dos perfis DBA da OLT em instantâneos. Não pergunta nada ao equipamento. */
export async function POST(req: Request) {
  if (!sameOrigin(req)) return NextResponse.json({ detail: "forbidden" }, { status: 403 });
  const f = await req.formData();
  const olt = String(f.get("olt") ?? "");
  if (!UUID.test(olt)) return NextResponse.json({ detail: "not found" }, { status: 404 });
  const r = await apiPost(`/v1/olts/${olt}/profiles/sync`, JSON.stringify({}), { "Content-Type": "application/json" });
  const to = (q: string) => `/rede/perfis?olt=${olt}&${q}`;
  if (r.status === 200) {
    const j = r.json as { created?: number; unchanged?: number; absent?: number } | null;
    return back(req, to(`ok=sincronizado&n=${Math.min(999, Number(j?.created ?? 0))}&u=${Math.min(999, Number(j?.unchanged ?? 0))}&a=${Math.min(999, Number(j?.absent ?? 0))}`));
  }
  const text = JSON.stringify(r.json ?? {});
  if (r.status === 403) return back(req, to("erro=permissao"));
  if (r.status === 409) return back(req, to(`erro=${text.includes("no_read") ? "semleitura" : text.includes("read_too_old") ? "leituraantiga" : text.includes("older_than_applied") ? "maisnova" : "identidade"}`));
  return back(req, to("erro=falha"));
}
