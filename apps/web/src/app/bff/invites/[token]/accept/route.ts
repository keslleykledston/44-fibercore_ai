import { sameOrigin } from "@/lib/csrf";
import { clientIp } from "@/lib/bff";
import { reply } from "@/lib/mfa-bff";

const API = process.env.API_INTERNAL_URL ?? "http://api-core:8000";
const TOKEN = /^[A-Za-z0-9_-]{20,100}$/;
const KNOWN = new Set(["password_short", "password_weak", "password_long", "invite_used", "invite_revoked", "invite_expired", "invite_invalid", "account_inactive", "already_member", "reset_not_allowed", "details_required"]);

/** Aceitar um convite ou trocar a senha por um link: SEM sessão. O link é a credencial; a API limita as tentativas por link e por origem. */
export async function POST(req: Request, ctx: { params: Promise<{ token: string }> }) {
  if (!sameOrigin(req)) return reply({ error: "forbidden" }, 403);
  const { token } = await ctx.params;
  if (!TOKEN.test(token)) return reply({ error: "invite_invalid" }, 404);
  const raw = await req.text();
  if (raw.length > 2048) return reply({ error: "failed" }, 413);
  let b: { name?: unknown; password?: unknown };
  try { b = JSON.parse(raw); } catch { return reply({ error: "failed" }, 400); }
  if (typeof b.password !== "string" || b.password.length < 1 || b.password.length > 256) return reply({ error: "details_required" }, 400);
  const name = typeof b.name === "string" && b.name.trim() ? b.name.trim().slice(0, 100) : undefined;
  const ip = clientIp(req);
  const res = await fetch(`${API}/v1/invites/${token}/accept`, {
    method: "POST", cache: "no-store",
    headers: { "content-type": "application/json", ...(ip ? { "x-forwarded-for": ip } : {}) },
    body: JSON.stringify({ name, password: b.password }),
  });
  let json: { detail?: string; purpose?: string } | null = null;
  try { json = await res.json(); } catch { /* sem corpo */ }
  if (res.status === 200) return reply({ ok: true, purpose: json?.purpose ?? "invite" });
  const detail = String(json?.detail ?? "");
  if (res.status === 401) return reply({ error: "invalid_credentials" }, 401);
  if (res.status === 429) return reply({ error: "throttled" }, 429);
  if (KNOWN.has(detail)) return reply({ error: detail }, [404, 409, 410, 422].includes(res.status) ? res.status : 400);
  if (res.status === 503) return reply({ error: "unavailable" }, 503);
  return reply({ error: "failed" }, 502);
}

export const dynamic = "force-dynamic";
