import type { Cpe } from "./types";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export const isUuid = (s: string) => UUID.test(s);

export type CpeFilters = { q: string; vendor: string; model: string; protocol: string; freshness: "" | "fresh" | "stale" | "unknown" };
type Raw = { q?: string; vendor?: string; model?: string; protocol?: string; freshness?: string };

const text = (s?: string) => (s ?? "").trim().slice(0, 64);

/** Filtros da lista de CPEs a partir da query string: só texto curto; freshness só aceita os três valores conhecidos. */
export function parseCpeFilters(r: Raw): CpeFilters {
  const f = r.freshness === "fresh" || r.freshness === "stale" || r.freshness === "unknown" ? r.freshness : "";
  return { q: text(r.q), vendor: text(r.vendor), model: text(r.model), protocol: text(r.protocol), freshness: f };
}

const has = (hay: string | null | undefined, needle: string) => (hay ?? "").toLowerCase().includes(needle.toLowerCase());

/** Filtra a lista já carregada (as chaves de comparação nunca vão para a API). */
export function filterCpes(cpes: Cpe[], f: CpeFilters): Cpe[] {
  return cpes.filter((c) =>
    (!f.q || has(c.canonical_serial, f.q) || c.bindings.some((b) => has(b.external_id, f.q))) &&
    (!f.vendor || (c.vendor ?? "") === f.vendor) && (!f.model || (c.model ?? "") === f.model) &&
    (!f.protocol || c.bindings.some((b) => b.protocol === f.protocol)) &&
    (!f.freshness || c.freshness === f.freshness));
}

export const distinct = (xs: (string | null | undefined)[]) => [...new Set(xs.filter((x): x is string => !!x))].sort((a, b) => a.localeCompare(b, "pt-BR"));

const METRIC: Record<string, string> = {
  wan_link_status: "Enlace da WAN", wan_connection_status: "Conexão da WAN", uptime_seconds: "Tempo ligado", wifi_radio_enabled: "Rádio Wi-Fi ligado", wifi_channel: "Canal Wi-Fi",
};
export const metricLabel = (m: string) => METRIC[m] ?? m;

/** Valor de uma métrica em texto curto (nunca HTML: o React escapa). */
export function metricValue(metric: string, v: unknown): string {
  if (metric === "uptime_seconds" && typeof v === "number") {
    const d = Math.floor(v / 86400), h = Math.floor((v % 86400) / 3600), m = Math.floor((v % 3600) / 60);
    return d ? `${d} d ${h} h` : h ? `${h} h ${m} min` : `${m} min`;
  }
  if (typeof v === "boolean") return v ? "Sim" : "Não";
  if (v === null || v === undefined) return "—";
  return typeof v === "string" ? v.slice(0, 120) : JSON.stringify(v).slice(0, 120);
}

export const PROTOCOL: Record<string, string> = { tr069: "TR-069 (GenieACS)", usp: "TR-369 (USP)" };
export const protocolLabel = (p: string) => PROTOCOL[p] ?? p;

export const EDGE_STATUS: Record<string, string> = { online: "Online", offline: "Sem sinal do Edge", unknown: "Sem batimento", revoked: "Revogado" };
