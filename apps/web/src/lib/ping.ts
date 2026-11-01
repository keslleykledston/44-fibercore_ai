/** Teste de ping (TR-143 IPPing, ADR-0039). Só formato e texto: quem decide é a API. Sem dado = "—", nunca 0. Não há DNS nem jitter nestes modelos: a tela diz isso em vez de inventar. */
export type PingTarget = { id: string; label: string; target_kind: "CORE" | "INTERNET"; region: string; ready: boolean };
export type PingCaps = { bench_target: boolean; offered: boolean; reason: string | null; targets: PingTarget[]; ready: boolean; repetitions: number; timeout_ms: number; per_hour: number };
export type PingRun = {
  id: string; target_id: string; status: string; created_at: string; sent: number | null; success: number | null; failure: number | null;
  loss_pct: number | null; avg_ms: number | null; min_ms: number | null; max_ms: number | null; spread_ms: number | null; reason: string | null;
};

const ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const CODE = /^[a-z][a-z0-9_]{0,59}$/;
const TG = /^[a-z0-9][a-z0-9-]{1,30}$/;
export const PING_ACTIVE = new Set(["awaiting_approval", "queued", "collecting"]);

const cnt = (v: unknown): number | null => (typeof v === "number" && Number.isInteger(v) && v >= 0 && v <= 10 ? v : null);
const ms = (v: unknown): number | null => (typeof v === "number" && Number.isInteger(v) && v >= 0 && v <= 86_400_000 ? v : null);

export function readPingCaps(d: unknown): PingCaps | null {
  const o = d as { bench_target?: unknown; test?: { offered?: unknown; reason?: unknown }; targets?: unknown; ready?: unknown; shape?: { repetitions?: unknown; timeout_ms?: unknown }; limits?: { per_cpe_per_hour?: unknown } } | null;
  if (!o || typeof o !== "object" || !o.test || typeof o.test.offered !== "boolean" || !Array.isArray(o.targets) || o.targets.length > 8) return null;
  const reason = o.test.reason;
  if (reason !== null && !(typeof reason === "string" && CODE.test(reason))) return null;
  const ts: PingTarget[] = [];
  for (const t of o.targets as PingTarget[]) {
    if (!t || !TG.test(t.id) || typeof t.label !== "string" || t.label.length > 60 || (t.target_kind !== "CORE" && t.target_kind !== "INTERNET") || typeof t.ready !== "boolean") return null;
    ts.push({ id: t.id, label: t.label, target_kind: t.target_kind, region: String(t.region ?? "").slice(0, 40), ready: t.ready });
  }
  return {
    bench_target: o.bench_target === true, offered: o.test.offered, reason, targets: ts, ready: o.ready === true,
    repetitions: cnt(o.shape?.repetitions) ?? 5, timeout_ms: ms(o.shape?.timeout_ms) ?? 1000, per_hour: cnt(o.limits?.per_cpe_per_hour) ?? 6,
  };
}

export function readPingRuns(d: unknown): PingRun[] | null {
  const o = d as { items?: unknown } | null;
  if (!o || !Array.isArray(o.items) || o.items.length > 20) return null;
  const out: PingRun[] = [];
  for (const r of o.items as PingRun[]) {
    if (!r || !ID.test(r.id) || !TG.test(r.target_id) || typeof r.status !== "string" || !CODE.test(r.status)) return null;
    out.push({
      id: r.id, target_id: r.target_id, status: r.status, created_at: String(r.created_at), sent: cnt(r.sent), success: cnt(r.success), failure: cnt(r.failure),
      loss_pct: typeof r.loss_pct === "number" && r.loss_pct >= 0 && r.loss_pct <= 100 ? r.loss_pct : null, avg_ms: ms(r.avg_ms), min_ms: ms(r.min_ms), max_ms: ms(r.max_ms), spread_ms: ms(r.spread_ms),
      reason: typeof r.reason === "string" && CODE.test(r.reason) ? r.reason : null,
    });
  }
  return out;
}

export const PING_STATUS_TEXT: Record<string, string> = {
  awaiting_approval: "Aguardando aprovação de outra pessoa (Operações)", queued: "Na fila para o Edge", collecting: "Em teste",
  completed: "Concluído", inconclusive: "Inconclusivo", error: "Erro no aparelho", failed: "Falhou", unknown: "Resultado incerto", cancelled: "Cancelado", expired: "Expirou sem executar",
};

export const PING_BLOCKED_TEXT: Record<string, string> = {
  not_permitted: "Seu papel não permite pedir testes de ping.",
  operation_not_homologated: "Este aparelho ainda não foi homologado para o teste de ping. Hoje ele só vale para o aparelho de bancada, com autorização prévia.",
  capability_not_observed: "Este modelo e firmware ainda não têm homologação registrada para o teste de ping.",
  target_unavailable: "O destino escolhido não está disponível.", cpe_busy: "Já existe um teste em andamento neste aparelho.",
  rate_limited: "Limite de testes por hora neste aparelho atingido; tente mais tarde.", feature_disabled: "O teste de ping está desligado para este provedor.",
  edge_support_missing: "O Edge ainda não suporta o teste de ping.",
};

export const PING_REASON_TEXT: Record<string, string> = {
  device_error: "O aparelho informou erro ao executar o teste.", no_counts: "O aparelho não informou quantos pacotes recebeu.", counts_mismatch: "As contagens do aparelho não batem com os 5 envios do teste.",
  no_times: "O aparelho não informou os tempos de resposta.", times_inconsistent: "Os tempos do aparelho são incoerentes (média fora de mínimo–máximo).",
  invalid_result: "O relatório do Edge não tinha o formato esperado e foi descartado.", wan_not_connected: "A WAN de serviço da ONT não estava conectada; nada foi enviado ao aparelho.",
  ping_not_started: "O teste não chegou a começar.", timeout: "Sem resultado dentro do prazo.", outcome_unknown: "Não foi possível confirmar o que aconteceu; o alvo fica travado até conferência.",
  edge_error: "O Edge reportou uma falha.", target_unknown: "O Edge não conhece este destino.", ping_disabled: "O teste de ping está desligado no Edge.",
};

export const msText = (n: number | null): string => (n === null ? "—" : `${n.toLocaleString("pt-BR")} ms`);
export const lossText = (n: number | null): string => (n === null ? "—" : `${n.toLocaleString("pt-BR", { maximumFractionDigits: 1 })} %`);
