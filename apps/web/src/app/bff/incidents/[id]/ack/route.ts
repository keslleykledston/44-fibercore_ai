import { NextResponse } from "next/server";
import { apiPost } from "@/lib/api";
import { sameOrigin } from "@/lib/csrf";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Reconhece um incidente (grava só a ciência de uma pessoa, auditada; não faz nada na rede). Same-origin; o token HttpOnly não chega ao navegador. */
export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  if (!sameOrigin(req)) return NextResponse.json({ detail: "forbidden" }, { status: 403 });
  const { id } = await params;
  if (!UUID.test(id)) return NextResponse.json({ detail: "not found" }, { status: 404 });
  const r = await apiPost(`/v1/incidents/${id}/ack`);
  const status = [200, 401, 403, 404, 409].includes(r.status) ? r.status : 502;
  return NextResponse.json({ ok: r.status === 200 }, { status, headers: { "cache-control": "no-store" } });
}
