import { apiPost } from "@/lib/api";
import { reply } from "@/lib/mfa-bff";
import { isResponse, readJson, strList, teamFailure } from "@/lib/team-bff";

/** Registra um webhook de saída (ADR-0051 D2). A resposta traz o segredo UMA vez. */
export async function POST(req: Request) {
  const b = await readJson(req);
  if (isResponse(b)) return b;
  const events = strList(b.events, 5);
  if (typeof b.name !== "string" || b.name.trim().length < 2 || b.name.length > 60 || typeof b.url !== "string" || b.url.length < 10 || b.url.length > 500 || !events || events.length === 0) return reply({ error: "bad_request" }, 400);
  const r = await apiPost("/v1/webhooks", JSON.stringify({ name: b.name.trim(), url: b.url.trim(), events }), { "content-type": "application/json" });
  if (r.status === 201) { const j = r.json as { id?: string; secret?: string }; return reply({ ok: true, id: j.id, secret: j.secret }, 201); }
  return teamFailure(r.status, r.json);
}

export const dynamic = "force-dynamic";
