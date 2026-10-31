import { apiSafe } from "@/lib/api";
import { reply } from "@/lib/mfa-bff";
import { buildQuick } from "@/lib/onu-quick";
import type { Onu360, OnuCustomer } from "@/lib/types";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Resumo rápido de UMA ONU: compõe no servidor as rotas que já existem (ONU 360 + assinante). A falha do assinante não derruba o resto; a da ONU, sim. Somente leitura. */
export async function GET(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  if (!UUID.test(id)) return reply({ error: "bad_request" }, 400);
  const [o, cu] = await Promise.all([apiSafe<Onu360>(`/v1/onus/${id}`), apiSafe<OnuCustomer>(`/v1/onus/${id}/customer`)]);
  if (o.data) return reply({ model: buildQuick(o.data, cu) });
  if (o.status === 403) return reply({ error: "forbidden" }, 403);
  if (o.status === 404) return reply({ error: "not_found" }, 404);
  if (o.status === 401) return reply({ error: "session" }, 401);
  return reply({ error: "failed" }, 502);
}

export const dynamic = "force-dynamic";
