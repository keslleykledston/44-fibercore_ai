import { apiPost } from "@/lib/api";
import { sameOrigin } from "@/lib/csrf";
import { reply } from "@/lib/mfa-bff";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const OPS = new Set(["reboot_cpe", "set_wifi_ssid"]); // as únicas ações da tela do CPE
const SSID = /^BANCADA-[A-Z0-9]{1,16}$/;
const KEY = /^[A-Za-z0-9_.:-]{8,128}$/;

/** Pede uma ação do CPE. A API decide tudo (permissão, capacidade, portão de escrita); aqui só formato e códigos estáveis. */
export async function POST(req: Request, ctx: { params: Promise<{ id: string; op: string }> }) {
  if (!sameOrigin(req)) return reply({ error: "forbidden" }, 403);
  const { id, op } = await ctx.params;
  if (!UUID.test(id) || !OPS.has(op)) return reply({ error: "bad_request" }, 400);
  const raw = await req.text();
  if (raw.length > 1024) return reply({ error: "bad_request" }, 413);
  let body: { key?: unknown; ssid?: unknown };
  try { body = JSON.parse(raw); } catch { return reply({ error: "bad_request" }, 400); }
  if (typeof body.key !== "string" || !KEY.test(body.key)) return reply({ error: "bad_request" }, 400);
  let params: Record<string, string> = {};
  if (op === "set_wifi_ssid") {
    if (typeof body.ssid !== "string" || !SSID.test(body.ssid)) return reply({ error: "bad_request" }, 400);
    params = { ssid: body.ssid };
  }
  const r = await apiPost(`/v1/cpes/${id}/actions/${op}`, JSON.stringify({ params }), { "content-type": "application/json", "Idempotency-Key": body.key });
  if (r.status === 200) {
    const j = r.json as { outcome?: string; reason?: string | null; job?: { id?: string; status?: string } } | null;
    return reply({ ok: true, outcome: j?.outcome ?? "submitted", reason: j?.reason ?? null, job_id: j?.job?.id ?? null, job_status: j?.job?.status ?? null });
  }
  const detail = String((r.json as { detail?: string } | null)?.detail ?? "");
  if (r.status === 409 && (detail === "capability_not_observed" || detail === "not_permitted")) return reply({ error: detail }, 409);
  if (r.status === 404) return reply({ error: "not_found" }, 404);
  if (r.status === 401) return reply({ error: "session" }, 401);
  if (r.status === 403) return reply({ error: "forbidden" }, 403);
  if (r.status === 422) return reply({ error: "bad_request" }, 400);
  return reply({ error: "failed" }, 502);
}

export const dynamic = "force-dynamic";
