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

export async function apiLogin(email: string, password: string, clientIp?: string): Promise<{ token: string | null; status: number }> {
  const res = await fetch(`${API}/v1/auth/token`, {
    method: "POST", // o IP do cliente vem do proxy de borda (Caddy) e é repassado para o throttle por origem da API
    headers: { "content-type": "application/json", ...(clientIp ? { "x-forwarded-for": clientIp } : {}) }, body: JSON.stringify({ email, password }), cache: "no-store",
  });
  if (!res.ok) return { token: null, status: res.status };
  return { token: ((await res.json()) as { access_token: string }).access_token, status: 200 };
}

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
