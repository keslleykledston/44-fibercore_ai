import { apiSafe } from "@/lib/api";
import { reply } from "@/lib/mfa-bff";
import { readForm } from "@/lib/ont-config";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Formulários de configuração do aparelho, como este usuário os vê (somente leitura). A API valida e a tela só repassa o formato fechado. */
export async function GET(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  if (!UUID.test(id)) return reply({ error: "bad_request" }, 400);
  const r = await apiSafe<unknown>(`/v1/cpes/${id}/ont-config/form-schema`);
  if (r.data) {
    const form = readForm(r.data);
    return form ? reply({ form }) : reply({ error: "failed" }, 502);
  }
  if (r.status === 403) return reply({ error: "disabled" }, 403);
  if (r.status === 404) return reply({ error: "not_found" }, 404);
  if (r.status === 401) return reply({ error: "session" }, 401);
  return reply({ error: "failed" }, 502);
}

export const dynamic = "force-dynamic";
