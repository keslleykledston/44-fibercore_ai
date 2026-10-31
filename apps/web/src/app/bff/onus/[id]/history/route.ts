import { apiSafe } from "@/lib/api";
import { featuresOn } from "@/lib/features";
import { reply } from "@/lib/mfa-bff";
import type { OnuHistory } from "@/lib/types";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Histórico de 30 dias de UMA ONU para a aba "Histórico" do painel de gestão. Só repassa a rota que já existe (somente leitura); sob a flag do painel (`onu_quick_inspector`). */
export async function GET(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  if (!UUID.test(id)) return reply({ error: "bad_request" }, 400);
  if (!(await featuresOn("onu_quick_inspector"))) return reply({ error: "disabled" }, 403);
  const h = await apiSafe<OnuHistory>(`/v1/onus/${id}/history?days=30&limit=12`);
  if (h.data) return h.data.onu_id.toLowerCase() === id.toLowerCase() ? reply({ history: h.data }) : reply({ error: "failed" }, 502);   // a resposta tem de ser da ONU pedida
  if (h.status === 403) return reply({ error: "forbidden" }, 403);
  if (h.status === 404) return reply({ error: "not_found" }, 404);
  if (h.status === 401) return reply({ error: "session" }, 401);
  return reply({ error: "failed" }, 502);
}

export const dynamic = "force-dynamic";
