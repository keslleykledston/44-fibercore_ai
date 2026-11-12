import { NextResponse } from "next/server";
import { apiPost } from "@/lib/api";
import { UUID } from "@/lib/fleet";

/**
 * Chave pública de selagem de um Edge e o estado da confirmação (ADR-0045), para o navegador selar. Rota fina: só repassa à API os campos NÃO secretos (a chave pública não é segredo).
 * Leitura same-origin (Fetch Metadata); com o recurso desligado responde 404, como se a rota não existisse.
 */
export async function GET(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const site = req.headers.get("sec-fetch-site");
  if (site && site !== "same-origin") return NextResponse.json({ detail: "forbidden" }, { status: 403, headers: { "cache-control": "no-store" } });
  const { id } = await params;
  if (!UUID.test(id)) return NextResponse.json({ detail: "not found" }, { status: 404 });
  const r = await apiPost(`/v1/fleet/edges/${id}/seal-key`, undefined, {}, "GET");
  const h = { "cache-control": "no-store" };
  if (r.status === 200) {
    const k = (r.json ?? {}) as Record<string, unknown>;
    const pick = ["tenant_id", "edge_id", "edge_name", "state", "key_id", "public_key", "fingerprint", "reported_at", "confirmed_at", "server_time", "max_window_seconds"];
    return NextResponse.json(Object.fromEntries(pick.map((f) => [f, k[f] ?? null])), { headers: h });
  }
  const disabled = r.status === 403 && JSON.stringify(r.json ?? {}).includes("feature_disabled");
  return NextResponse.json({ detail: disabled ? "not found" : r.status === 403 ? "forbidden" : r.status === 401 ? "unauthorized" : "falha" }, { status: disabled ? 404 : [401, 403, 404].includes(r.status) ? r.status : 502, headers: h });
}
