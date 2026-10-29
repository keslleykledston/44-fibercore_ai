import { NextResponse } from "next/server";
import { apiSafe } from "@/lib/api";
import type { CustomerRow } from "@/lib/types";

/** Busca de cliente por nome para a busca global (⌘K). Devolve só id e nome: sem documento, contrato ou contato. O acesso é auditado pela API. */
export async function GET(req: Request) {
  const q = (new URL(req.url).searchParams.get("q") ?? "").trim().slice(0, 64);
  if (q.length < 3) return NextResponse.json({ items: [] }, { headers: { "cache-control": "no-store" } });
  const r = await apiSafe<CustomerRow[]>(`/v1/customers?limit=5&q=${encodeURIComponent(q)}`);
  if (r.data) return NextResponse.json({ items: r.data.map((c) => ({ id: c.id, display_name: c.display_name })) }, { headers: { "cache-control": "no-store" } });
  // sem permissão ou API fora: a busca global segue funcionando só com telas e ONU
  return NextResponse.json({ items: [], unavailable: true }, { status: r.status === 403 ? 200 : 502, headers: { "cache-control": "no-store" } });
}
