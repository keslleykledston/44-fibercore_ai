/** Teste de banda TR-143 (ADR-0038). Só formato e texto: quem decide é a API. A tela só mostra o que tem o formato fechado, nunca preenche o que falta (sem dado = "—", nunca 0). */
export type SpeedDirection = "download" | "upload";
export type SpeedEndpoint = { id: string; label: string; target_kind: "CORE" | "INTERNET"; region: string; ready: boolean };
export type SpeedDirState = { offered: boolean; reason: string | null };
export type SpeedCaps = { bench_target: boolean; directions: Record<SpeedDirection, SpeedDirState>; endpoints: SpeedEndpoint[]; profiles: string[]; ready: boolean };
export type SpeedRun = {
  id: string; group_id: string; direction: SpeedDirection; endpoint_id: string; profile: string; status: string; created_at: string;
  mbps: number | null; bytes: number | null; duration_ms: number | null; reliable: boolean; reason: string | null; basis: string | null;
};

const ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const CODE = /^[a-z][a-z0-9_]{0,59}$/;
const EP = /^[a-z0-9][a-z0-9-]{1,30}$/;
export const PROFILES = ["10mb", "50mb", "200mb"] as const;
export const PROFILE_TEXT: Record<string, string> = { "10mb": "10 MB", "50mb": "50 MB", "200mb": "200 MB" };
export const ACTIVE = new Set(["awaiting_approval", "queued", "collecting"]);

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) && v > 0 ? v : null);

export function readCaps(d: unknown): SpeedCaps | null {
  const o = d as SpeedCaps | null;
  if (!o || typeof o !== "object" || !o.directions || !Array.isArray(o.endpoints) || o.endpoints.length > 8 || !Array.isArray(o.profiles)) return null;
  const dir = (x: unknown): SpeedDirState | null => {
    const s = x as SpeedDirState | null;
    return s && typeof s.offered === "boolean" && (s.reason === null || (typeof s.reason === "string" && CODE.test(s.reason))) ? { offered: s.offered, reason: s.reason } : null;
  };
  const dl = dir(o.directions.download), ul = dir(o.directions.upload);
  if (!dl || !ul) return null;
  const eps = o.endpoints.every((e) => EP.test(e.id) && typeof e.label === "string" && e.label.length <= 60 && (e.target_kind === "CORE" || e.target_kind === "INTERNET") && typeof e.ready === "boolean");
  if (!eps) return null;
  return {
    bench_target: o.bench_target === true, directions: { download: dl, upload: ul }, ready: o.ready === true,
    endpoints: o.endpoints.map((e) => ({ id: e.id, label: e.label, target_kind: e.target_kind, region: String(e.region ?? "").slice(0, 40), ready: e.ready })),
    profiles: o.profiles.filter((p): p is string => typeof p === "string" && (PROFILES as readonly string[]).includes(p)),
  };
}

export function readRuns(d: unknown): SpeedRun[] | null {
  const o = d as { items?: unknown } | null;
  if (!o || !Array.isArray(o.items) || o.items.length > 20) return null;
  const out: SpeedRun[] = [];
  for (const r of o.items as SpeedRun[]) {
    if (!r || !ID.test(r.id) || !ID.test(r.group_id) || (r.direction !== "download" && r.direction !== "upload") || !EP.test(r.endpoint_id) || typeof r.status !== "string" || !CODE.test(r.status)) return null;
    out.push({
      id: r.id, group_id: r.group_id, direction: r.direction, endpoint_id: r.endpoint_id, profile: r.profile, status: r.status, created_at: String(r.created_at),
      mbps: num(r.mbps), bytes: num(r.bytes), duration_ms: num(r.duration_ms), reliable: r.reliable === true, reason: typeof r.reason === "string" && CODE.test(r.reason) ? r.reason : null, basis: typeof r.basis === "string" ? r.basis : null,
    });
  }
  return out;
}

export const DIRECTION_TEXT: Record<SpeedDirection, string> = { download: "Download", upload: "Upload" };

export const STATUS_TEXT: Record<string, string> = {
  awaiting_approval: "Aguardando aprovação de outra pessoa (Operações)", queued: "Na fila para o Edge", collecting: "Em teste",
  completed: "Concluído", partial: "Parcial", inconclusive: "Inconclusivo", error: "Erro no aparelho",
  failed: "Falhou", unknown: "Resultado incerto", cancelled: "Cancelado", expired: "Expirou sem executar",
};

/** Por que não se pode pedir este teste agora, em linguagem de operação. */
export const BLOCKED_TEXT: Record<string, string> = {
  not_permitted: "Seu papel não permite pedir testes de banda.",
  operation_not_homologated: "Este aparelho ainda não foi homologado para o teste de banda. Hoje ele só vale para o aparelho de bancada, com autorização prévia.",
  capability_not_observed: "Este modelo e firmware ainda não têm homologação registrada para o teste de banda.",
  redirect_unverified: "Falta a evidência de que o aparelho não segue redirecionamento (ou a ACL de saída da WAN de serviço).",
  endpoint_unavailable: "O destino escolhido não está disponível.", endpoint_unhealthy: "O destino de teste não respondeu à última verificação do Edge.",
  pon_unknown: "Não há vínculo confirmado entre a ONU e este roteador, então a PON não é conhecida e o limite por PON não pode ser garantido.",
  cpe_busy: "Já existe um teste em andamento neste aparelho.", pon_busy: "Já existe um teste em andamento nesta PON.", tenant_busy: "O limite de testes simultâneos do provedor foi atingido.",
  group_mismatch: "Este teste não combina com o anterior (mesmo destino e tamanho).", feature_disabled: "O teste de banda está desligado para este provedor.",
  edge_support_missing: "O Edge ainda não suporta o teste de banda.",
};

export const REASON_TEXT: Record<string, string> = {
  too_short: "Medição curta demais (menos de 3 s): não representa a capacidade da linha.", short_transfer: "Transferiu menos do que o tamanho escolhido.",
  no_timestamps: "O aparelho não informou os horários do teste.", invalid_duration: "Duração inválida informada pelo aparelho.", no_bytes: "O aparelho não informou quantos bytes transferiu.",
  bytes_exceed_profile: "Os contadores do aparelho não batem com o tamanho do teste.", implausible_rate: "Taxa acima do possível: contadores ou relógio do aparelho incoerentes.",
  negligible_rate: "Quase nada foi transferido.", device_error: "O aparelho informou erro ao executar o teste.", not_completed: "O aparelho não terminou o teste.",
  timeout: "Sem resultado dentro do prazo; o aparelho pode ainda estar gerando tráfego.", outcome_unknown: "Não foi possível confirmar o que aconteceu; o alvo fica travado até conferência.",
  invalid_result: "O relatório do Edge não tinha o formato esperado e foi descartado.", edge_error: "O Edge reportou uma falha.", speed_not_started: "O teste não chegou a começar.",
};

export const mbpsText = (n: number | null): string => (n === null ? "—" : `${n.toLocaleString("pt-BR", { maximumFractionDigits: 2 })} Mbps`);
export const qualityText = (r: SpeedRun): string => (r.status === "completed" ? "Confiável" : r.status === "partial" ? "Parcial" : r.status === "inconclusive" ? "Inconclusivo" : "—");
