import { randomUUID } from "node:crypto";
import { NextResponse } from "next/server";
import { apiPost } from "@/lib/api";
import { back } from "@/lib/bff";
import { sameOrigin } from "@/lib/csrf";
import { UUID } from "@/lib/fleet";

/** Pede o teste de conexão (leitura somente leitura da identidade, pelo Edge). Nada é enviado à OLT daqui; a nuvem aplica o orçamento e o cache. Uma chave de idempotência por pedido evita gastar duas vezes. */
export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  if (!sameOrigin(req)) return NextResponse.json({ detail: "forbidden" }, { status: 403 });
  const { id } = await params;
  if (!UUID.test(id)) return NextResponse.json({ detail: "not found" }, { status: 404 });
  const r = await apiPost(`/v1/fleet/olts/${id}/connection-test`, undefined, { "Idempotency-Key": `fleet-${randomUUID()}` });
  const to = (q: string) => `/rede/frota/${id}?${q}`;
  if (r.status === 200) {
    const o = (r.json as { outcome?: string } | null)?.outcome;
    return back(req, to(`ok=${o === "cached" ? "testecache" : "testepedido"}`));
  }
  const txt = JSON.stringify(r.json ?? {});
  if (r.status === 429) return back(req, to("erro=orcamento"));
  if (r.status === 403) return back(req, to(`erro=${txt.includes("feature_disabled") ? "desligado" : "permissao"}`));
  if (r.status === 409) return back(req, to("erro=consulta"));
  return back(req, to("erro=falha"));
}
