// Política de MFA e escopo por site/OLT (ADR-0049): rótulos e frases PURAS.
import type { MemberScope, SecurityPolicy } from "./types";

export const ROLE_NAME: Record<string, string> = {
  isp_admin: "Administrador do provedor", access_manager: "Gestor de acesso", engineer: "Engenheiro", noc_n2: "Operador NOC (nível 2)",
  noc_n1: "Operador NOC (nível 1)", support: "Atendimento", auditor: "Auditor", platform_support: "Suporte da plataforma",
};
export const roleName = (r: string) => ROLE_NAME[r] ?? r;

/** Quantas pessoas ainda sem verificação serão levadas a cadastrá-la se esta escolha for salva. */
export function affected(policy: Pick<SecurityPolicy, "floor" | "members_without_mfa">, chosen: string[]): number {
  const roles = new Set([...policy.floor, ...chosen]);
  return Object.entries(policy.members_without_mfa).reduce((n, [r, c]) => n + (roles.has(r) ? c : 0), 0);
}

export const sameSet = (a: string[], b: string[]) => a.length === b.length && [...a].sort().join() === [...b].sort().join();

export function scopeBadge(s: { restricted: boolean; pops: number; olts: number } | undefined): string {
  if (!s || !s.restricted) return "Escopo: provedor inteiro";
  const parts = [s.pops ? `${s.pops} ${s.pops === 1 ? "site" : "sites"}` : "", s.olts ? `${s.olts} ${s.olts === 1 ? "OLT" : "OLTs"}` : ""].filter(Boolean);
  return `Restrito: ${parts.join(", ") || "nada"}`;
}

export const scopeNotice = (olts: number | null | undefined) => `Seu acesso é restrito a ${olts ?? 0} ${olts === 1 ? "OLT" : "OLTs"}.`;

/** Marca/desmarca um id mantendo a lista sem repetição. */
export const toggle = (list: string[], id: string, on: boolean) => (on ? (list.includes(id) ? list : [...list, id]) : list.filter((x) => x !== id));

export const canSaveScope = (pops: string[], olts: string[]) => pops.length + olts.length > 0 && pops.length + olts.length <= 200;

export const optionsLabel = (o: MemberScope["options"], id: string) => o.olts.find((x) => x.id === id)?.name ?? o.pops.find((x) => x.id === id)?.name ?? "(removido)";

export const SCOPE_EXPLAIN = "Quem tem escopo só LÊ a rede dentro do escopo (as OLTs e os sites escolhidos, e o que está ligado a eles). Perde clientes, equipe, auditoria, políticas e qualquer ação em equipamento. A mudança vale na próxima tela, sem a pessoa entrar de novo.";
