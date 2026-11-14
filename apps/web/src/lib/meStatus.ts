import "server-only";
import { cache } from "react";
import { getSession } from "./session";
import type { MeInfo } from "./types";

const API = process.env.API_INTERNAL_URL ?? "http://api-core:8000";

/** A pessoa logada (permissões efetivas e escopo). Uma consulta por requisição. Usa fetch direto (sem os redirecionamentos de `api()`): o menu também aparece na tela em que a pessoa ainda
 *  precisa ativar o MFA, e aí a API responde 403. Qualquer falha = nada sabido: o menu fica como sempre foi (nunca esconde por engano). */
export const meStatus = cache(async (): Promise<MeInfo | null> => {
  try {
    const { token, workspace } = await getSession();
    if (!token) return null;
    const res = await fetch(`${API}/v1/auth/me`, { cache: "no-store", headers: { Authorization: `Bearer ${token}`, ...(workspace ? { "X-Workspace-ID": workspace } : {}) } });
    return res.ok ? ((await res.json()) as MeInfo) : null;
  } catch { return null; }
});

export const can = (me: MeInfo | null, perm: string) => !!me?.permissions.some((p) => p.name === perm);
