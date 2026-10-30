import { apiSafe } from "@/lib/api";
import { reply } from "@/lib/mfa-bff";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Estado de UM pedido de consulta da OLT (só leitura). Só passam o estado, a categoria de falha e o resultado tipado, nada mais do job. */
export async function GET(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  if (!UUID.test(id)) return reply({ error: "bad_request" }, 400);
  const r = await apiSafe<{ operation: string; status: string; result: { detail?: string | null; data?: unknown } | null }>(`/v1/jobs/${id}`);
  if (r.data) {
    if (r.data.operation !== "olt_query") return reply({ error: "not_found" }, 404);
    return reply({ status: r.data.status, detail: r.data.result?.detail ?? null, data: r.data.result?.data ?? null });
  }
  if (r.status === 404) return reply({ error: "not_found" }, 404);
  if (r.status === 403) return reply({ error: "forbidden" }, 403);
  return reply({ error: "failed" }, 502);
}

export const dynamic = "force-dynamic";
