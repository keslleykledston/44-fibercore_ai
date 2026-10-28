import { NextResponse } from "next/server";
import { apiPost } from "@/lib/api";
import { sameOrigin } from "@/lib/csrf";

/** Respostas dos endpoints de MFA carregam segredo/códigos: nunca cacheáveis. */
export const NO_STORE = { "Cache-Control": "no-store, max-age=0", Pragma: "no-cache" } as const;
export const reply = (body: unknown, status = 200) => NextResponse.json(body, { status, headers: NO_STORE });

/** Mensagens estáveis para o painel; o detalhe da API (que pode citar conta/limites) não é repassado. */
export function failure(status: number, json?: unknown): NextResponse {
  // A 401 from the API means either a wrong password/code or an expired access token; only the latter should send the user to reload.
  if (status === 401) return reply({ error: (json as { detail?: string } | null)?.detail === "invalid or missing credentials" ? "session" : "invalid" }, 401);
  if (status === 409) return reply({ error: "conflict" }, 409);
  if (status === 429) return reply({ error: "throttled" }, 429);
  if (status === 503) return reply({ error: "unavailable" }, 503);
  return reply({ error: "failed" }, 502);
}

type Field = { name: string; min: number; max: number };

/** Lê o corpo JSON com limite e valida os campos; devolve a resposta de erro ou os valores. */
export async function readFields(req: Request, fields: Field[]): Promise<NextResponse | Record<string, string>> {
  if (!sameOrigin(req)) return reply({ error: "forbidden" }, 403);
  if (!(req.headers.get("content-type") ?? "").includes("application/json")) return reply({ error: "bad_request" }, 415);
  const raw = await req.text();
  if (raw.length > 2048) return reply({ error: "bad_request" }, 413);
  let body: Record<string, unknown>;
  try { body = JSON.parse(raw); } catch { return reply({ error: "bad_request" }, 400); }
  const out: Record<string, string> = {};
  for (const f of fields) {
    const v = body?.[f.name];
    if (typeof v !== "string" || v.length < f.min || v.length > f.max) return reply({ error: "bad_request" }, 400);
    out[f.name] = f.name === "code" ? v.trim() : v;
  }
  return out;
}

export async function forward(path: string, payload: Record<string, string>) {
  return apiPost(path, JSON.stringify(payload), { "content-type": "application/json" });
}
