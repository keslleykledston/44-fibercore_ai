import type { OfflineBasis } from "./types";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const PON = /^[0-9/]{1,32}$/;

export type OfflineFilters = { minHours: number; oltId: string | null; ponPath: string | null; includeStale: boolean };

type Raw = { min_hours?: string; olt_id?: string; pon_path?: string; include_stale?: string };

/** Filtros da tela a partir da query string: tudo que não passar na validação volta ao padrão (nunca vai para a API). */
export function parseOfflineFilters(q: Raw): OfflineFilters {
  const h = Number(q.min_hours);
  return {
    minHours: q.min_hours !== undefined && q.min_hours !== "" && Number.isFinite(h) && h >= 0 && h <= 8760 ? h : 24,
    oltId: q.olt_id && UUID.test(q.olt_id) ? q.olt_id : null,
    ponPath: q.pon_path && PON.test(q.pon_path) ? q.pon_path : null,
    includeStale: q.include_stale === "1",
  };
}

/** Query da API (e do CSV) para esses filtros. */
export function offlineQuery(f: OfflineFilters, extra: Record<string, string> = {}): string {
  const p = new URLSearchParams({ min_hours: String(f.minHours), ...extra });
  if (f.oltId) p.set("olt_id", f.oltId);
  if (f.ponPath) p.set("pon_path", f.ponPath);
  if (f.includeStale) p.set("include_stale", "true");
  return p.toString();
}

/** "3 d 4 h", "5 h", "20 min": a idade da queda em palavras. */
export function humanHours(h: number): string {
  if (h < 1) return `${Math.max(1, Math.round(h * 60))} min`;
  if (h < 48) return `${Math.round(h)} h`;
  const d = Math.floor(h / 24), r = Math.round(h - d * 24);
  return r ? `${d} d ${r} h` : `${d} d`;
}

/** O que cada base significa, em linguagem de operador: a tela nunca apresenta um início estimado como exato. */
export const BASIS: Record<OfflineBasis, { label: string; hint: string }> = {
  transition_observed: { label: "Exato", hint: "O Edge viu a ONU online e depois fora do ar." },
  olt_reported: { label: "Informado pela OLT", hint: "Horário de queda que a própria OLT informa; o relógio da OLT pode divergir alguns minutos." },
  since_last_online: { label: "No máximo", hint: "Visto online pela última vez nesse instante: a queda dura no máximo isso." },
};
