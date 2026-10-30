/** Consultas somente leitura da OLT (ADR-0029): textos estáveis e leitura dos resultados TIPADOS. Nada aqui executa algo; a API e o Edge decidem. */
export type OltQueryItem = { id: string; title: string; scope: "global" | "slot" | "pon" | "onu"; fields: string[]; validated: boolean; offered: boolean; reason: string | null };
export type OltQueryCatalog = { olt_id: string; enabled: boolean; limits: { user_per_hour: number; tenant_per_hour: number }; items: OltQueryItem[] };
export type OltVersion = { product: string; version: string; patch: string; uptime_seconds: number };
export type OltBoard = { boards: { slot: number; name: string; status: string }[]; empty_slots: number[] };

export const QUERY_UNAVAILABLE: Record<string, string> = {
  not_permitted: "seu papel não pede consultas à OLT.",
  query_not_enabled: "ainda não liberada para uso (falta a validação supervisionada).",
  olt_query_disabled: "desligada para este provedor.",
};

export const QUERY_ERROR: Record<string, string> = {
  olt_query_disabled: "As consultas à OLT estão desligadas para este provedor.",
  query_not_enabled: "Esta consulta ainda não foi liberada.",
  olt_without_edge: "Esta OLT não tem um Edge associado.",
  olt_query_quota: "Limite de consultas por hora atingido. Tente mais tarde.",
  not_permitted: "Seu papel não pede consultas à OLT.",
  forbidden: "Seu papel não permite esta consulta.",
  session: "Sua sessão expirou. Recarregue a página e entre de novo.",
  not_found: "Esta OLT não existe mais.",
  bad_request: "Consulta inválida.",
  failed: "Falha inesperada. Tente em instantes.",
};

/** Por que um pedido terminou sem resultado: categorias do Edge (nunca texto do equipamento). */
export const QUERY_FAILED: Record<string, string> = {
  expired: "A consulta venceu antes de a janela da coleta abrir.",
  olt_busy: "A OLT estava ocupada ou em espera após uma falha; nada foi repetido.",
  device_rejected: "O equipamento recusou o comando.",
  no_parser: "Esta consulta ainda não devolve resultado tipado.",
  bad_output: "A resposta do equipamento não tinha o formato esperado e não foi usada.",
  invalid_result: "O Edge devolveu um resultado fora do formato esperado e ele foi descartado.",
  stale_owner: "A OLT mudou de Edge; o pedido foi descartado.",
  lease_lost: "O Edge perdeu a autorização de uso da OLT durante a janela.",
  window_closed: "A janela da coleta terminou antes de a consulta começar.",
  timeout: "A consulta passou do tempo disponível na sessão.",
  queue_full: "A fila do Edge para esta OLT está cheia.",
  persist_error: "O Edge não conseguiu gravar o resultado.",
  restart_after_claim: "O Edge reiniciou durante a consulta; o resultado é desconhecido e ela não foi repetida.",
  claim_abandoned: "A consulta ficou sem resposta do Edge; o resultado é desconhecido e ela não foi repetida.",
};

export function uptimeText(seconds: number): string {
  const d = Math.floor(seconds / 86400), h = Math.floor((seconds % 86400) / 3600), m = Math.floor((seconds % 3600) / 60);
  return `${d} d ${h} h ${m} min`;
}

const S = /^[A-Za-z0-9._ -]{1,64}$/;
/** Só devolve o resultado se TEM o formato fechado; qualquer outra coisa é descartada (a tela nunca mostra texto livre do equipamento). */
export function readVersion(d: unknown): OltVersion | null {
  const o = d as OltVersion | null;
  return o && typeof o === "object" && [o.product, o.version, o.patch].every((s) => typeof s === "string" && S.test(s)) && Number.isInteger(o.uptime_seconds) && o.uptime_seconds >= 0 ? o : null;
}
export function readBoard(d: unknown): OltBoard | null {
  const o = d as OltBoard | null;
  if (!o || typeof o !== "object" || !Array.isArray(o.boards) || !Array.isArray(o.empty_slots)) return null;
  const ok = o.boards.length <= 18 && o.boards.every((b) => Number.isInteger(b.slot) && typeof b.name === "string" && S.test(b.name) && typeof b.status === "string" && S.test(b.status)) && o.empty_slots.every((n) => Number.isInteger(n));
  return ok ? o : null;
}
