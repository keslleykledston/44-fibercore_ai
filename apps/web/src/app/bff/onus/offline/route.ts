import { NextResponse } from "next/server";
import { apiRaw } from "@/lib/api";
import { offlineQuery, parseOfflineFilters } from "@/lib/offline";

/** CSV do relatório de ONUs offline (só leitura). Os filtros são revalidados aqui; o token HttpOnly nunca chega ao navegador. */
export async function GET(req: Request) {
  const u = new URL(req.url);
  const f = parseOfflineFilters({
    min_hours: u.searchParams.get("min_hours") ?? undefined, olt_id: u.searchParams.get("olt_id") ?? undefined,
    pon_path: u.searchParams.get("pon_path") ?? undefined, include_stale: u.searchParams.get("include_stale") ?? undefined,
  });
  const r = await apiRaw(`/v1/onus/offline?${offlineQuery(f, { format: "csv", limit: "5000" })}`);
  if (r.status !== 200) return NextResponse.json({ detail: r.status === 403 ? "forbidden" : "error" }, { status: [401, 403].includes(r.status) ? r.status : 502 });
  const h: Record<string, string> = {
    "content-type": "text/csv; charset=utf-8", "cache-control": "no-store", "content-disposition": 'attachment; filename="onus-offline.csv"',
  };
  for (const k of ["x-excluded-stale", "x-excluded-unknown-start", "x-truncated"]) { const v = r.headers.get(k); if (v !== null) h[k] = v; }
  return new NextResponse(r.body, { status: 200, headers: h });
}
