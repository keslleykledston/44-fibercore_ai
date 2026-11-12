import { NextResponse } from "next/server";
import { apiPost } from "@/lib/api";
import { sameOrigin } from "@/lib/csrf";
import { UUID } from "@/lib/fleet";

// Credenciais da OLT (ADR-0045). Rotas FINAS: o navegador já cifrou; o BFF só confere o FORMATO do envelope e repassa. Texto claro nunca chega aqui (e o corpo nunca é registrado nem repetido numa resposta).
const KEY_ID = /^[0-9a-f]{16}$/;
const SEALED = /^[A-Za-z0-9_-]{100,2048}$/;
const MAX_BODY = 4096;
const noStore = { "cache-control": "no-store" };
const KINDS = new Set(["ssh_login", "snmp_community", "olt_connection"]);   // ADR-0046: a conexão da OLT segue o mesmo canal (a API decide a permissão e a flag de cada kind)
const STABLE = /^[a-z][a-z0-9_]{0,59}$/;

/** Código estável da API (nunca texto livre) ou "falha". */
function codeOf(json: unknown): string {
  const d = (json as { detail?: unknown } | null)?.detail;
  return typeof d === "string" && STABLE.test(d) ? d : "falha";
}

export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  if (!sameOrigin(req)) return NextResponse.json({ detail: "forbidden" }, { status: 403, headers: noStore });
  const { id } = await params;
  if (!UUID.test(id)) return NextResponse.json({ detail: "not found" }, { status: 404, headers: noStore });
  if (!(req.headers.get("content-type") ?? "").toLowerCase().startsWith("application/json")) return NextResponse.json({ detail: "invalid" }, { status: 415, headers: noStore });
  const text = await req.text();
  if (text.length > MAX_BODY) return NextResponse.json({ detail: "too_large" }, { status: 413, headers: noStore });
  let b: Record<string, unknown>;
  try { b = JSON.parse(text) as Record<string, unknown>; } catch { return NextResponse.json({ detail: "invalid" }, { status: 422, headers: noStore }); }
  const keys = Object.keys(b ?? {}).sort().join(",");
  if (keys !== "delivery_id,expires_at,key_id,kind,sealed" ||   // exatamente estes campos: nenhum campo extra (um texto claro enviado por engano é recusado aqui, sem eco)
      typeof b.delivery_id !== "string" || !UUID.test(b.delivery_id) || typeof b.kind !== "string" || !KINDS.has(b.kind) || typeof b.key_id !== "string" || !KEY_ID.test(b.key_id) ||
      typeof b.expires_at !== "number" || !Number.isInteger(b.expires_at) || typeof b.sealed !== "string" || !SEALED.test(b.sealed)) {
    return NextResponse.json({ detail: "invalid" }, { status: 422, headers: noStore });
  }
  const r = await apiPost(`/v1/fleet/olts/${id}/secret-deliveries`, JSON.stringify({ delivery_id: b.delivery_id, kind: b.kind, key_id: b.key_id, expires_at: b.expires_at, sealed: b.sealed }), { "Content-Type": "application/json" });
  if (r.status === 202) {
    const j = (r.json ?? {}) as { id?: string; status?: string };
    return NextResponse.json({ id: j.id ?? null, status: j.status ?? "PENDING" }, { status: 202, headers: noStore });
  }
  const code = codeOf(r.json);
  if (r.status === 403) return NextResponse.json({ detail: code === "feature_disabled" ? "not found" : "forbidden" }, { status: code === "feature_disabled" ? 404 : 403, headers: noStore });
  return NextResponse.json({ detail: r.status === 401 ? "unauthorized" : code }, { status: [401, 404, 409, 422, 429].includes(r.status) ? r.status : 502, headers: noStore });
}

/** Últimas entregas (estado e código; nunca o texto cifrado: a API não o devolve). */
export async function GET(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const site = req.headers.get("sec-fetch-site");
  if (site && site !== "same-origin") return NextResponse.json({ detail: "forbidden" }, { status: 403, headers: noStore });
  const { id } = await params;
  if (!UUID.test(id)) return NextResponse.json({ detail: "not found" }, { status: 404, headers: noStore });
  const r = await apiPost(`/v1/fleet/olts/${id}/secret-deliveries`, undefined, {}, "GET");
  if (r.status === 200) return NextResponse.json({ items: ((r.json as { items?: unknown[] } | null)?.items ?? []) }, { headers: noStore });
  const disabled = r.status === 403 && codeOf(r.json) === "feature_disabled";
  return NextResponse.json({ detail: disabled ? "not found" : r.status === 401 ? "unauthorized" : "falha" }, { status: disabled ? 404 : [401, 403, 404].includes(r.status) ? r.status : 502, headers: noStore });
}
