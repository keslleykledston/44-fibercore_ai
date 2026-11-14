/** Organizações da plataforma (ADR-0046 D1): tipos, textos em português e o mapa de erros. Funções puras (testadas sem navegador); nada aqui toca a rede. */
export type PlatformStatus = { operator: boolean; mfa_recent: boolean };
export type PlatformOrg = {
  id: string; name: string; status: string; created_at: string; edges: number; olts: number; onus: number;
  edges_total: number; edges_online: number; olts_stale: number; last_heartbeat_at: string | null; flags_on: number;
  created_by: string | null; created_via: "screen" | "cli"; invite_state: "pending" | "accepted" | "expired" | "revoked" | null; api_trail: boolean | null;
};
export type PlatformOrgList = { total: number; next: { before_at: string; before_id: string } | null; items: PlatformOrg[] };
export type OrgFeature = { feature: string; default: boolean; enabled: boolean; source: "tenant" | "default"; owner_only: boolean };
export type LimitKey = "max_edges" | "max_olts" | "max_members" | "ingest_per_minute" | "ingest_burst";
export type LimitValues = Record<LimitKey, number | null>;
export type OrgLimits = { values: LimitValues; defaults: Record<LimitKey, number>; effective: Record<LimitKey, number>; usage: { edges: number; olts: number; members: number; invites_open?: number }; updated_at: string | null };
export type OrgHistory = { at: string; action: string; actor: string | null; detail: { reason?: string; from?: string | Partial<LimitValues>; to?: string | Partial<LimitValues>; feature?: string; name?: string } };
/** ADR-0050: o pedido de encerramento da organização (a tela só PEDE; quem exporta e apaga é o dono, no host). */
export type OrgClosure = {
  state: "requested" | "cancelled" | "closed"; reason: string; requested_at: string; earliest_close_at: string; cancelled_at: string | null;
  export_at: string | null; export_sha256: string | null; export_bytes: number | null; ready: boolean;
};
export type ClosureRecord = {
  tenant_id: string; name: string; state: "requested" | "cancelled" | "closed"; reason: string; requested_at: string; earliest_close_at: string; closed_at: string | null;
  deleted_rows: Record<string, number> | null; export_sha256: string | null;
};
export type ClosureList = { items: ClosureRecord[] };
export type PlatformOrgDetail = {
  tenant_id: string; name: string; status: string; created_at: string; edges: number; edges_total: number; edges_online: number; olts: number; olts_stale: number; onus: number;
  last_heartbeat_at: string | null; flags_on: number; limits?: OrgLimits; closure?: OrgClosure | null; catalog: OrgFeature[]; history: OrgHistory[]; unknown_overrides: string[];
};
export type CreatedOrg = { tenant_id: string; name: string; invite: { id: string; state: string; role: string; email: string; expires_at: string; token: string } };

export const FLASH_COOKIE = "fc_org_flash";   // o link do convite aparece UMA vez, num cookie HttpOnly de 2 minutos preso a /plataforma (a URL nunca o carrega)
export const FLASH_PATH = "/plataforma";
export const FLASH_SECONDS = 120;
const TOKEN = /^[A-Za-z0-9_-]{20,100}$/;

export const ORG_ERRORS: Record<string, string> = {
  duplicada: "Já existe uma organização com esse nome (a comparação ignora maiúsculas e espaços repetidos). Escolha outro nome.",
  limite: "Limite de 5 organizações por hora atingido. Tente de novo mais tarde.",
  mfa: "O segundo fator precisa ter sido confirmado nos últimos 10 minutos. Confirme abaixo e envie de novo.",
  nome: "O nome da organização precisa ter de 2 a 60 caracteres, sem caracteres de controle.",
  email: "O e-mail do primeiro administrador não é válido.",
  admin: "O nome do primeiro administrador pode ter até 100 caracteres, sem caracteres de controle.",
  invalido: "Algum campo está fora do formato. Confira o nome e o e-mail.",
  permissao: "Esta conta não é operadora da plataforma.",
  codigo: "Código inválido ou já usado. Use o próximo código do autenticador.",
  semmfa: "Esta conta ainda não ativou o MFA. Ative em Conta → Segurança e volte aqui.",
  tentativas: "Muitas tentativas. Aguarde alguns minutos.",
  falha: "Não foi possível concluir. Nada foi criado; tente novamente.",
  naoencontrada: "Organização não encontrada.",
  motivo: "Informe o motivo, de 3 a 200 caracteres, sem caracteres de controle.",
  flag: "Recurso desconhecido ou estado inválido.",
  somentedono: "Este recurso escreve na rede ou usa IA: só o dono do sistema o liga, pela linha de comando. Aqui só é possível desligar.",
  precondicao: "Este recurso ainda não tem o suporte do Edge necessário para ser ligado.",
  limites: "Algum limite está fora da faixa permitida. Use números inteiros dentro das faixas indicadas em cada campo.",
  semlimite: "Preencha pelo menos um campo ou marque \"Padrão\" em algum deles.",
  naosuspensa: "Só uma organização suspensa pode ser encerrada. Suspenda primeiro.",
  demo: "Uma organização de demonstração nunca é encerrada por esta tela.",
  pedidoexiste: "Já existe um pedido de encerramento aberto para esta organização.",
  sempedido: "Não há pedido de encerramento aberto para cancelar.",
};
export const ORG_FLASH: Record<string, string> = {
  mfaok: "Segundo fator confirmado.", oculto: "Link do convite ocultado.", suspensa: "Organização suspensa. Usuários e Edge dela recebem bloqueio até a reativação.",
  reativada: "Organização reativada. O acesso volta na hora, sem novo login.", renomeada: "Nome da organização alterado.", flagok: "Recurso atualizado.",
  semmudanca: "Nada mudou: já estava nesse estado.", limitesok: "Limites atualizados.",
  encerramentopedido: "Pedido de encerramento aberto. Nada foi apagado: a carência de 7 dias começou.", encerramentocancelado: "Pedido de encerramento cancelado.",
};

/** Erro da API → código curto da tela. Nunca repassa texto da API (só um código estável). */
export function orgError(status: number, json: unknown): string {
  const detail = (json as { detail?: unknown } | null)?.detail;
  if (status === 403) return detail === "mfa_recent_required" ? "mfa" : detail === "owner_only_feature" ? "somentedono" : "permissao";
  if (status === 404) return detail === "closure_not_found" ? "sempedido" : "naoencontrada";
  if (status === 409) {
    return detail === "organization_name_taken" ? "duplicada" : detail === "organization_not_suspended" ? "naosuspensa" : detail === "organization_is_demo" ? "demo" : detail === "closure_exists" ? "pedidoexiste" : "falha";
  }
  if (status === 429) return "limite";
  if (status === 422) {
    if (detail === "organization_name_invalid") return "nome";
    if (detail === "organization_email_invalid") return "email";
    if (detail === "organization_admin_name_invalid") return "admin";
    if (detail === "organization_reason_invalid") return "motivo";
    if (detail === "limits_invalid") return "limites";
    if (detail === "unknown_feature" || detail === "feature_invalid" || detail === "feature_state_invalid") return "flag";
    if (detail === "feature_precondition") return "precondicao";
    if (Array.isArray(detail)) {
      const field = (detail[0] as { loc?: unknown[] } | undefined)?.loc?.[1];
      return field === "name" ? "nome" : field === "admin_email" ? "email" : field === "admin_name" ? "admin" : field === "reason" ? "motivo" : field === "state" ? "flag" : "invalido";
    }
    return "invalido";
  }
  return "falha";
}

/** Erro do passo do segundo fator (a API de step-up) → código curto da tela. */
export function stepUpError(status: number): string {
  return status === 401 ? "codigo" : status === 409 ? "semmfa" : status === 429 ? "tentativas" : "falha";
}

export const INVITE_STATE: Record<string, string> = {
  pending: "Pendente (vale 72 h)", accepted: "Aceito", expired: "Expirou (peça ao dono do sistema)", revoked: "Revogado",
};
export const inviteLabel = (s: PlatformOrg["invite_state"]) => (s ? INVITE_STATE[s] ?? s : "—");
export const ORG_STATUS: Record<string, string> = { active: "Ativa", suspended: "Suspensa" };

/** O que o cookie de aviso guarda (base64url de JSON). */
export function encodeFlash(c: CreatedOrg): string {
  return Buffer.from(JSON.stringify({ n: c.name, e: c.invite.email, s: c.invite.state, x: c.invite.expires_at, t: c.invite.token })).toString("base64url");
}
export type Flash = { name: string; email: string; state: string; expires: string; token: string };
export function decodeFlash(raw: string | undefined): Flash | null {
  if (!raw) return null;
  try {
    const j = JSON.parse(Buffer.from(raw, "base64url").toString("utf8")) as Record<string, unknown>;
    if (typeof j.n !== "string" || typeof j.e !== "string" || typeof j.s !== "string" || typeof j.x !== "string" || typeof j.t !== "string" || !TOKEN.test(j.t)) return null;
    return { name: j.n.slice(0, 60), email: j.e.slice(0, 254), state: j.s, expires: j.x, token: j.t };
  } catch { return null; }
}
/** Só o CAMINHO: a origem completa é a que o navegador usa (OrgInviteLink); nenhum cabeçalho de host da requisição entra no link (Codex r2). */
export const invitePath = (token: string) => `/convite/${token}`;

/** `?antes=<instante>~<id>` da tela → consulta da API. Só passa instante ISO e UUID no formato certo; qualquer outra coisa é ignorada (volta à primeira página). */
const ISO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|[+-]\d{2}:\d{2})$/;
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export function cursorQuery(raw: string): string {
  const [at, id] = raw.split("~");
  if (!at || !id || !ISO.test(at) || !UUID_RE.test(id)) return "";
  return new URLSearchParams({ before_at: at, before_id: id }).toString();
}

export const UUID_FORMAT = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export const FEATURE_FORMAT = /^[a-z][a-z0-9_]{1,63}$/;
export const FEATURE_STATES = ["on", "off", "default"] as const;
export type FeatureState = (typeof FEATURE_STATES)[number];
export const FEATURE_STATE_LABEL: Record<FeatureState, string> = { on: "Ligar", off: "Desligar", default: "Voltar ao padrão" };
/** Estados que a tela oferece para um recurso: os que escrevem na rede ou usam IA só podem ser desligados aqui. */
export const featureChoices = (f: { owner_only: boolean }): FeatureState[] => (f.owner_only ? ["off", "default"] : ["on", "off", "default"]);
/** Avisos curtos de recursos que dependem da configuração LOCAL do Edge (a nuvem não a enxerga). */
export const FEATURE_NOTES: Record<string, string> = {
  fleet_provision: "Exige a seção managed_olts no Edge.", acs_registry: "Exige nbi_cloud_id no config do Edge.",
};
export const ACTION_LABEL: Record<string, string> = {
  "platform.organization.created": "Criada", "platform.organization.suspended": "Suspensa", "platform.organization.reactivated": "Reativada",
  "platform.organization.renamed": "Renomeada", "platform.feature.set": "Recurso", "platform.limits.set": "Limites alterados",
  "platform.closure.requested": "Encerramento pedido", "platform.closure.cancelled": "Encerramento cancelado",
};
/** ADR-0047 D3: os cinco limites, a faixa que o banco aceita e o rótulo da tela. A organização nunca os altera; é o operador. */
export const LIMIT_FIELDS: { key: LimitKey; label: string; min: number; max: number; unit: string }[] = [
  { key: "max_edges", label: "Edges", min: 0, max: 10000, unit: "" },
  { key: "max_olts", label: "OLTs", min: 0, max: 100000, unit: "" },
  { key: "max_members", label: "Membros", min: 0, max: 10000, unit: "" },
  { key: "ingest_per_minute", label: "Ingestão por minuto", min: 1, max: 60000, unit: "lotes/min" },
  { key: "ingest_burst", label: "Ingestão em rajada", min: 1, max: 10000, unit: "lotes" },
];
const LIMIT_RANGE = Object.fromEntries(LIMIT_FIELDS.map((f) => [f.key, f])) as Record<LimitKey, (typeof LIMIT_FIELDS)[number]>;
/**
 * Formulário de limites → corpo da API. Campo vazio = não mexe; caixa "Padrão" marcada = `null` (volta ao padrão do código); número inteiro dentro da faixa = define.
 * Fora da faixa ou não inteiro → `{ erro: "limites" }`; nada preenchido → `{ erro: "semlimite" }` (o servidor valida de novo).
 */
export function limitsPayload(get: (name: string) => string): { limits: Partial<LimitValues> } | { erro: "limites" | "semlimite" } {
  const out: Partial<LimitValues> = {};
  for (const f of LIMIT_FIELDS) {
    if (get(`default_${f.key}`) !== "") { out[f.key] = null; continue; }
    const raw = get(f.key).trim();
    if (raw === "") continue;
    if (!/^\d{1,7}$/.test(raw)) return { erro: "limites" };
    const n = Number(raw);
    if (n < LIMIT_RANGE[f.key].min || n > LIMIT_RANGE[f.key].max) return { erro: "limites" };
    out[f.key] = n;
  }
  return Object.keys(out).length ? { limits: out } : { erro: "semlimite" };
}
const LIMIT_SHORT: Record<LimitKey, string> = { max_edges: "Edges", max_olts: "OLTs", max_members: "Membros", ingest_per_minute: "ingestão/min", ingest_burst: "rajada" };
/** De→para dos limites, só das chaves que mudaram ("OLTs: padrão → 5"). */
export function limitsDiff(from: Partial<LimitValues> | string | undefined, to: Partial<LimitValues> | string | undefined): string {
  if (typeof from !== "object" || typeof to !== "object" || !from || !to) return "";
  const word = (v: number | null | undefined) => (v === null || v === undefined ? "padrão" : String(v));
  return (Object.keys(LIMIT_SHORT) as LimitKey[]).filter((k) => (from[k] ?? null) !== (to[k] ?? null)).map((k) => `${LIMIT_SHORT[k]}: ${word(from[k])} → ${word(to[k])}`).join("; ");
}
const STATE_WORD: Record<string, string> = { on: "ligado", off: "desligado", default: "padrão", active: "ativa", suspended: "suspensa" };
/** Linha do histórico → texto curto (motivo e de→para). Só chaves conhecidas; nada de HTML. */
export function historyText(h: OrgHistory): string {
  const d = h.detail ?? {};
  if (h.action === "platform.limits.set") return [limitsDiff(d.from, d.to), d.reason ? `motivo: ${d.reason}` : ""].filter(Boolean).join(" · ");
  const change = typeof d.from === "string" && typeof d.to === "string" ? `${d.feature ? `${d.feature}: ` : ""}${STATE_WORD[d.from] ?? d.from} → ${STATE_WORD[d.to] ?? d.to}` : d.name ?? "";
  return [change, d.reason ? `motivo: ${d.reason}` : ""].filter(Boolean).join(" · ");
}
export const CLOSURE_STATE: Record<string, string> = { requested: "Pedido aberto", cancelled: "Pedido cancelado", closed: "Encerrada" };
/** Aspas simples para o shell: o nome da organização pode ter apóstrofo ou espaço; nada entra em linha de comando sem isto. */
export const shellQuote = (v: string) => `'${v.replace(/'/g, `'\\''`)}'`;
/** Os dois comandos do DONO, no host do servidor (ADR-0050 D2/D3). A tela não executa nada: só mostra o que o dono roda. */
export function closureCommands(id: string, name: string): { exportar: string; encerrar: string } {
  return {
    exportar: `org-export ${id} --out ARQUIVO.tar.gz`,
    encerrar: `org-close ${id} --confirm-name ${shellQuote(name)} --export-file ARQUIVO.tar.gz`,
  };
}
/** Carência vencida? (compara o instante da API com o relógio do servidor da tela; a API e a CLI conferem de novo.) */
export const graceOver = (c: { earliest_close_at: string } | null | undefined, now: number = Date.now()) => !!c && new Date(c.earliest_close_at).getTime() <= now;
export const rowsDeleted = (r: Record<string, number> | null) => (r ? Object.values(r).reduce((a, b) => a + b, 0) : 0);
export const healthText = (o: { edges_online: number; edges_total: number; olts_stale: number }) =>
  `${o.edges_online}/${o.edges_total} Edge${o.edges_total === 1 ? "" : "s"} online · ${o.olts_stale} OLT${o.olts_stale === 1 ? "" : "s"} sem coleta`;
