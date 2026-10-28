import "server-only";
import { redirect } from "next/navigation";
import { getSession } from "./session";

const API = process.env.API_INTERNAL_URL ?? "http://api-core:8000";

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

/** Chamada server-side à API: o token HttpOnly nunca chega ao browser (ADR-0014). */
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const { token, workspace } = await getSession();
  if (!token) redirect("/login");
  const res = await fetch(`${API}${path}`, {
    ...init,
    cache: "no-store",
    headers: { ...(init.headers ?? {}), Authorization: `Bearer ${token}`, ...(workspace ? { "X-Workspace-ID": workspace } : {}) },
  });
  if (res.status === 401) redirect("/login");
  if (!res.ok) throw new ApiError(res.status, `API ${res.status}`);
  return (await res.json()) as T;
}

export async function apiSafe<T>(path: string): Promise<{ data: T | null; status: number }> {
  try { return { data: await api<T>(path), status: 200 }; }
  catch (e) { if (e instanceof ApiError) return { data: null, status: e.status }; throw e; }
}

export type LoginResult =
  | { kind: "session"; access: string; refresh: string; expiresIn: number }
  | { kind: "mfa"; mfaToken: string }
  | { kind: "error"; status: number };

type SessionBody = { access_token?: string; refresh_token?: string; expires_in?: number; mfa_required?: boolean; mfa_token?: string };

function parseSession(res: Response, body: SessionBody | null): LoginResult {
  if (!res.ok || !body) return { kind: "error", status: res.status };
  if (body.mfa_required && body.mfa_token) return { kind: "mfa", mfaToken: body.mfa_token };
  if (body.access_token && body.refresh_token) return { kind: "session", access: body.access_token, refresh: body.refresh_token, expiresIn: body.expires_in ?? 900 };
  return { kind: "error", status: 502 };
}

async function postJson(path: string, payload: unknown, clientIp?: string): Promise<LoginResult> {
  const res = await fetch(`${API}${path}`, {
    method: "POST", // o IP do cliente vem do proxy de borda e é repassado para o throttle por origem da API
    headers: { "content-type": "application/json", ...(clientIp ? { "x-forwarded-for": clientIp } : {}) }, body: JSON.stringify(payload), cache: "no-store",
  });
  let body: SessionBody | null = null;
  try { body = (await res.json()) as SessionBody; } catch { /* sem corpo */ }
  return parseSession(res, body);
}

export const apiLogin = (email: string, password: string, clientIp?: string) => postJson("/v1/auth/token", { email, password }, clientIp);
export const apiMfaVerify = (mfaToken: string, code: string, clientIp?: string) => postJson("/v1/auth/mfa/verify", { mfa_token: mfaToken, code }, clientIp);

/** POST server-side com o token da sessão. Devolve status e corpo JSON (se houver). */
export async function apiPost(path: string, body?: BodyInit, headers: Record<string, string> = {}): Promise<{ status: number; json: unknown }> {
  const { token, workspace } = await getSession();
  if (!token) return { status: 401, json: null };
  const res = await fetch(`${API}${path}`, {
    method: "POST", body, cache: "no-store",
    headers: { ...headers, Authorization: `Bearer ${token}`, ...(workspace ? { "X-Workspace-ID": workspace } : {}) },
  });
  let json: unknown = null;
  try { json = await res.json(); } catch { /* sem corpo */ }
  return { status: res.status, json };
}
