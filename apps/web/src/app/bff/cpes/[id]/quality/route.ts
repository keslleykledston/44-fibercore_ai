import { apiSafe } from "@/lib/api";
import { reply } from "@/lib/mfa-bff";
import { readCaps, readRuns } from "@/lib/quality";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Capacidades da leitura de qualidade deste aparelho + as últimas leituras. A API decide; aqui só o formato fechado e códigos estáveis. */
export async function GET(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  if (!UUID.test(id)) return reply({ error: "bad_request" }, 400);
  const [c, r] = await Promise.all([apiSafe<unknown>(`/v1/cpes/${id}/quality/capabilities`), apiSafe<unknown>(`/v1/cpes/${id}/quality/runs`)]);
  if (c.data && r.data) {
    const caps = readCaps(c.data), runs = readRuns(r.data);
    return caps && runs ? reply({ caps, runs }) : reply({ error: "failed" }, 502);
  }
  // as duas leituras são julgadas juntas e a falha de autorização/ausência vence: sessão > inexistente > recusa (recurso desligado ou sem permissão) > falha
  const sts = [c.status, r.status];
  if (sts.includes(401)) return reply({ error: "session" }, 401);
  if (sts.includes(404)) return reply({ error: "not_found" }, 404);
  if (sts.includes(403)) return reply({ error: "forbidden" }, 403);
  return reply({ error: "failed" }, 502);
}

export const dynamic = "force-dynamic";
