import { cookies } from "next/headers";
import { apiPost } from "@/lib/api";
import { sameOrigin } from "@/lib/csrf";
import { reply } from "@/lib/mfa-bff";
import { clearSessionCookies } from "@/lib/session";

const KNOWN = new Set(["password_short", "password_weak", "password_long", "password_same"]);

/** Troca a PRÓPRIA senha. A API encerra todas as sessões da conta; o painel limpa os cookies e a pessoa entra de novo. */
export async function POST(req: Request) {
  if (!sameOrigin(req)) return reply({ error: "forbidden" }, 403);
  const raw = await req.text();
  if (raw.length > 2048) return reply({ error: "failed" }, 413);
  let b: { current?: unknown; next?: unknown };
  try { b = JSON.parse(raw); } catch { return reply({ error: "failed" }, 400); }
  if (typeof b.current !== "string" || typeof b.next !== "string" || !b.current || !b.next || b.next.length > 256 || b.current.length > 256) return reply({ error: "details_required" }, 400);
  const r = await apiPost("/v1/auth/password", JSON.stringify({ current_password: b.current, new_password: b.next }), { "content-type": "application/json" });
  if (r.status === 200) {
    clearSessionCookies(await cookies());
    return reply({ ok: true });
  }
  const detail = String((r.json as { detail?: string } | null)?.detail ?? "");
  if (r.status === 401) return reply({ error: detail === "invalid credentials" ? "invalid_credentials" : "session" }, 401);
  if (r.status === 429) return reply({ error: "throttled" }, 429);
  if (r.status === 422 && KNOWN.has(detail)) return reply({ error: detail }, 422);
  if (r.status === 503) return reply({ error: "unavailable" }, 503);
  return reply({ error: "failed" }, 502);
}

export const dynamic = "force-dynamic";
