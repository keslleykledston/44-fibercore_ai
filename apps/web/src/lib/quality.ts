/** Diagnóstico de qualidade do serviço (QoS-001, ADR-0039). Só formato e texto: quem decide é a API. A tela mostra apenas o que tem o formato fechado e nunca preenche o que falta (sem dado = "sem leitura", nunca zero). */
export type QStatus = "valid" | "stale" | "not_supported" | "not_available" | "not_applicable" | "failed" | "inconclusive";
export type QMetric = {
  id: string; group: string; status: QStatus; value: string | number | boolean | null; unit: string | null; source: string; scope: string;
  instance: string | null; collected_at: string | null; freshness_s: number | null; judged: boolean | null;
};
export type QIndicator = { state: "ok" | "attention" | "stale" | "unknown"; metric_ids: string[] };
export type QHypothesis = { code: string; label: string; confidence: string; recommended_check: string; caveats: string[] };
export type QObservation = { code: string; scope: string };
export type QSummary = {
  state: "attention" | "no_anomalies_observed" | "insufficient_data"; observations: QObservation[];
  indicators: Record<"wan" | "optical" | "wifi" | "cpe", QIndicator>; note: string | null;
};
export type QRun = { id: string; mode: "quick" | "full"; created_at: string; metrics: QMetric[]; hypotheses: QHypothesis[]; summary: QSummary };
export type QCaps = { modes: { quick: { offered: boolean; reason: string | null } } };   // mesmo formato da API: o BFF e a tela leem pelo mesmo leitor

const ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const CODE = /^[a-z][a-z0-9_]{0,59}$/;
const UP = /^[A-Z][A-Z0-9_]{0,59}$/;
const MID = /^[a-z][a-z0-9_.]{0,59}$/;
const GROUPS: readonly string[] = ["WAN", "OPTICAL", "ETHERNET", "WIFI", "CPE", "CORE", "INTERNET"];
const SOURCES: readonly string[] = ["TR069_READ", "TR069_ACTIVE", "OLT_ADAPTER", "SD001", "ACS_CACHE"];
const SCOPES: readonly string[] = ["SERVICE_WAN", "MGMT_WAN", "WAN_UNCLASSIFIED", "LAN", "PON", "WIFI", "CPE"];
const CONF: readonly string[] = ["low", "medium", "high"];
const INST = /^[A-Za-z0-9_.:-]{1,40}$/;
const STATUSES: readonly string[] = ["valid", "stale", "not_supported", "not_available", "not_applicable", "failed", "inconclusive"];
const STATES: readonly string[] = ["ok", "attention", "stale", "unknown"];
const GLOBAL: readonly string[] = ["attention", "no_anomalies_observed", "insufficient_data"];
export const INDICATORS = ["wan", "optical", "wifi", "cpe"] as const;

const ISO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|[+-]\d{2}:\d{2})$/;
const isoOk = (v: unknown): v is string => typeof v === "string" && ISO.test(v) && !Number.isNaN(Date.parse(v));
const txt = (v: unknown, max: number): string | null => (typeof v === "string" && v.length > 0 && v.length <= max ? v : null);

export function readCaps(d: unknown): QCaps | null {
  const q = (d as { modes?: { quick?: { offered?: unknown; reason?: unknown } } } | null)?.modes?.quick;
  if (!q || typeof q.offered !== "boolean" || !(q.reason === null || (typeof q.reason === "string" && CODE.test(q.reason)))) return null;
  return { modes: { quick: { offered: q.offered, reason: q.reason } } };
}

function readMetric(m: QMetric): QMetric | null {
  if (!m || !MID.test(m.id) || !STATUSES.includes(m.status) || !GROUPS.includes(m.group) || !SOURCES.includes(m.source) || !SCOPES.includes(m.scope)) return null;
  if (m.instance !== null && m.instance !== undefined && (typeof m.instance !== "string" || !INST.test(m.instance))) return null;
  if (m.collected_at !== null && m.collected_at !== undefined && !isoOk(m.collected_at)) return null;
  if (m.freshness_s !== null && m.freshness_s !== undefined && (typeof m.freshness_s !== "number" || !Number.isFinite(m.freshness_s))) return null;
  if (m.unit !== null && m.unit !== undefined && (typeof m.unit !== "string" || !/^[A-Za-z%\/]{1,12}$/.test(m.unit))) return null;
  const keeps = m.status === "valid" || m.status === "stale";
  const v = m.value;
  if (keeps && v !== null && v !== undefined && !(typeof v === "boolean" || (typeof v === "number" && Number.isFinite(v)) || (typeof v === "string" && v.length <= 40 && /^[\w .:/-]*$/.test(v)))) return null;
  const judged = (m as unknown as { details?: { judged?: unknown } }).details?.judged;
  return {
    id: m.id, group: m.group, status: m.status, value: keeps && v !== undefined ? v : null, unit: m.unit ?? null, source: m.source, scope: m.scope, instance: m.instance ?? null,
    collected_at: m.collected_at ?? null, freshness_s: m.freshness_s !== null && m.freshness_s !== undefined && m.freshness_s >= 0 ? m.freshness_s : null,
    judged: typeof judged === "boolean" ? judged : null,
  };
}

export function readRun(r: unknown): QRun | null {
  const o = r as QRun | null;
  if (!o || !ID.test(o.id) || (o.mode !== "quick" && o.mode !== "full") || !Array.isArray(o.metrics) || o.metrics.length > 80 || !Array.isArray(o.hypotheses) || o.hypotheses.length > 12) return null;
  if (!isoOk(o.created_at)) return null;   // horário de leitura inválido: a resposta inteira é recusada, nunca "Invalid Date" na tela
  const s = o.summary;
  if (!s || !GLOBAL.includes(s.state) || !s.indicators || !Array.isArray(s.observations) || s.observations.length > 12 || !s.observations.every((x) => x && typeof x.code === "string" && UP.test(x.code) && SCOPES.includes(x.scope))) return null;
  const ind = {} as QSummary["indicators"];
  for (const k of INDICATORS) {
    const x = s.indicators[k];
    if (!x || !STATES.includes(x.state) || !Array.isArray(x.metric_ids)) return null;
    ind[k] = { state: x.state, metric_ids: x.metric_ids.filter((i): i is string => typeof i === "string" && MID.test(i)).slice(0, 40) };
  }
  const hyps = o.hypotheses.map((h) => {
    if (!h || typeof h.code !== "string" || !UP.test(h.code) || !Array.isArray(h.caveats) || h.caveats.length > 5) return null;
    const label = txt(h.label, 200), check = txt(h.recommended_check, 200), caveats = h.caveats.map((c) => txt(c, 200));
    if (!label || !check || caveats.some((c) => c === null) || !CONF.includes(h.confidence)) return null;
    return { code: h.code, label, confidence: h.confidence, recommended_check: check, caveats: caveats as string[] };
  });
  if (hyps.some((h) => h === null)) return null;   // hipótese malformada recusa a resposta inteira: nunca texto convertido à força
  if (s.note !== null && s.note !== undefined && txt(s.note, 200) === null) return null;
  const metrics = o.metrics.map(readMetric);
  if (metrics.some((m) => m === null)) return null;
  return {
    id: o.id, mode: o.mode, created_at: o.created_at,
    metrics: metrics as QMetric[],
    hypotheses: hyps as QHypothesis[],
    summary: {
      state: s.state, indicators: ind, note: s.note ? s.note : null,
      observations: s.observations as QObservation[],
    },
  };
}

export function readRuns(d: unknown): QRun[] | null {
  const o = d as { runs?: unknown } | null;
  if (!o || !Array.isArray(o.runs) || o.runs.length > 20) return null;
  const out = o.runs.map(readRun);
  return out.some((x) => x === null) ? null : (out as QRun[]);
}

export const GLOBAL_TEXT: Record<QSummary["state"], string> = {
  attention: "Atenção: há indício a verificar",
  no_anomalies_observed: "Nenhuma anomalia observada nos dados atuais",
  insufficient_data: "Dados insuficientes para avaliar",
};
export const INDICATOR_TITLE: Record<(typeof INDICATORS)[number], string> = { wan: "WAN", optical: "Óptica", wifi: "Wi‑Fi", cpe: "Equipamento" };
export const UNJUDGED_TEXT = "Leitura atual, sem faixa de referência";   // o nível óptico só é julgado com o perfil homologado da classe de ONU; sem ele, mostra-se o valor sem dizer "ok"
export const INDICATOR_TEXT: Record<QIndicator["state"], string> = { ok: "Sem anomalia observada", attention: "Atenção", stale: "Leitura antiga", unknown: "Sem leitura" };
export const STATUS_TEXT: Record<QStatus, string> = {
  valid: "Leitura atual", stale: "Leitura antiga", not_supported: "Não suportado neste modelo", not_available: "Sem leitura", not_applicable: "Não se aplica",
  failed: "Falhou", inconclusive: "Inconclusivo",
};
export const METRIC_TEXT: Record<string, string> = {
  "wan.link_status": "Enlace da WAN", "wan.connection_status": "Conexão da WAN", "cpe.uptime_s": "Tempo ligado", "wifi.radio_enabled": "Rádio Wi‑Fi ligado",
  "wifi.channel": "Canal Wi‑Fi", "optical.rx_dbm": "Nível óptico (RX)", "onu.status": "Estado da ONU na OLT",
  "speed.download_mbps": "Download (teste de banda)", "speed.upload_mbps": "Upload (teste de banda)",
};
export const OBSERVATION_TEXT: Record<string, string> = {
  WAN_LINK_DOWN: "O enlace da WAN informado pelo aparelho está fora do ar.", WAN_CONNECTION_NOT_UP: "A conexão da WAN informada pelo aparelho não está ativa.",
  ONU_NOT_ONLINE: "A OLT não vê a ONU online.",
};
export const SCOPE_TEXT: Record<string, string> = { WAN_UNCLASSIFIED: "WAN não classificada (serviço ou gerência)", SERVICE_WAN: "WAN de serviço", MGMT_WAN: "WAN de gerência", PON: "PON", WIFI: "Wi‑Fi", CPE: "Aparelho", LAN: "LAN" };
export const SOURCE_TEXT: Record<string, string> = { TR069_READ: "ACS (leitura)", TR069_ACTIVE: "ACS (teste ativo)", OLT_ADAPTER: "OLT", SD001: "teste de banda", ACS_CACHE: "ACS (cache)" };
/** "Fonte · idade" de um indicador: só as métricas que ele cita e que têm leitura (atual ou antiga). Com mais de uma, a idade é a da MAIS ANTIGA (a mais fresca esconderia a velha). Sem nenhuma: sem leitura. */
export function indicatorSource(ind: QIndicator, metrics: QMetric[]): string {
  const ms = metrics.filter((m) => ind.metric_ids.includes(m.id) && (m.status === "valid" || m.status === "stale"));
  if (ms.length === 0) return "Fonte: sem leitura";
  const sources = [...new Set(ms.map((m) => SOURCE_TEXT[m.source] ?? "outra fonte"))];
  const ages = ms.map((m) => m.freshness_s).filter((s): s is number => s !== null);
  const age = ages.length > 0 ? `${ms.length > 1 ? " · a mais antiga " : " · "}${ageText(Math.max(...ages))}` : "";
  return `Fonte: ${sources.join(" + ")}${age}`;
}
export const CONFIDENCE_TEXT: Record<string, string> = { low: "confiança baixa", medium: "confiança média", high: "confiança alta" };
export const LOAD_ERROR: Record<string, string> = {
  not_found: "Este aparelho não existe mais.",
  session: "Sua sessão expirou. Recarregue a página e entre de novo.", failed: "Não foi possível carregar o diagnóstico de qualidade agora.",
  forbidden: "O diagnóstico de qualidade não está disponível para você: o recurso está desligado para este provedor ou o seu papel não permite.",
};
export const REFUSAL_TEXT: Record<string, string> = {
  forbidden: "Seu papel não permite pedir a leitura de qualidade.", disabled: "O diagnóstico de qualidade está desligado para este provedor.",
  not_found: "Este aparelho não existe mais.",
};

export const valueText = (m: QMetric): string => {
  if (m.status !== "valid" && m.status !== "stale") return "—";
  if (m.value === null) return "—";
  if (typeof m.value === "boolean") return m.value ? "Sim" : "Não";
  const n = typeof m.value === "number" ? m.value.toLocaleString("pt-BR", { maximumFractionDigits: 2 }) : m.value;
  return m.unit ? `${n} ${m.unit}` : String(n);
};
export const ageText = (s: number | null): string => (s === null ? "" : s < 90 ? "agora há pouco" : s < 5400 ? `há ${Math.round(s / 60)} min` : s < 172800 ? `há ${Math.round(s / 3600)} h` : `há ${Math.round(s / 86400)} dias`);
