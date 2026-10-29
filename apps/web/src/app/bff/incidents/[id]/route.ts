import { NextResponse } from "next/server";
import { apiSafe } from "@/lib/api";
import type { IncidentDetail } from "@/lib/types";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Detalhe de um incidente para o painel lateral (o token HttpOnly nunca chega ao navegador). Só leitura. */
export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!UUID.test(id)) return NextResponse.json({ detail: "not found" }, { status: 404 });
  const r = await apiSafe<IncidentDetail>(`/v1/incidents/${id}`);
  if (r.data) return NextResponse.json(r.data, { headers: { "cache-control": "no-store" } });
  return NextResponse.json({ detail: r.status === 404 ? "not found" : "error" }, { status: [403, 404].includes(r.status) ? r.status : 502 });
}
