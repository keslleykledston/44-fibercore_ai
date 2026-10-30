import { apiPost } from "@/lib/api";
import { sameOrigin } from "@/lib/csrf";
import { reply } from "@/lib/mfa-bff";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const OPS = new Set(["reboot_cpe", "set_wifi_ssid", "onu_reset", "onu_deactivate"]);
const SSID = /^BANCADA-[A-Z0-9]{1,16}$/;
const KNOWN = new Set(["role_cannot_authorize", "target_not_bench", "target_write_locked", "bench_writes_disabled", "authorization_already_open", "edge_support_missing", "mfa_recent_required"]);

/** Autoriza UMA manobra de bancada (a API e o banco decidem tudo; aqui só formato e códigos estáveis). */
export async function POST(req: Request) {
  if (!sameOrigin(req)) return reply({ error: "forbidden" }, 403);
  const raw = await req.text();
  if (raw.length > 1024) return reply({ error: "bad_request" }, 413);
  let b: { cpe_id?: unknown; operation?: unknown; ssid?: unknown; minutes?: unknown };
  try { b = JSON.parse(raw); } catch { return reply({ error: "bad_request" }, 400); }
  const minutes = Number(b.minutes);
  if (typeof b.cpe_id !== "string" || !UUID.test(b.cpe_id) || typeof b.operation !== "string" || !OPS.has(b.operation) || !Number.isInteger(minutes) || minutes < 5 || minutes > 120) return reply({ error: "bad_request" }, 400);
  let params: Record<string, string> = {};
  if (b.operation === "set_wifi_ssid") {
    if (typeof b.ssid !== "string" || !SSID.test(b.ssid)) return reply({ error: "bad_request" }, 400);
    params = { ssid: b.ssid };
  }
  const r = await apiPost("/v1/bench/authorizations", JSON.stringify({ cpe_id: b.cpe_id, operation: b.operation, params, minutes }), { "content-type": "application/json" });
  if (r.status === 201) return reply({ ok: true }, 201);
  const detail = String((r.json as { detail?: string } | null)?.detail ?? "");
  if ([403, 409].includes(r.status) && KNOWN.has(detail)) return reply({ error: detail }, r.status);
  if (r.status === 401) return reply({ error: "session" }, 401);
  if (r.status === 403) return reply({ error: "forbidden" }, 403);
  if (r.status === 422) return reply({ error: "bad_request" }, 400);
  if (r.status === 503) return reply({ error: "unavailable" }, 503);
  return reply({ error: "failed" }, 502);
}

export const dynamic = "force-dynamic";
