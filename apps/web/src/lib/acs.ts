/** Cadastro de ACS por organização (ADR-0046 D2): tipos da API e textos em português. Funções puras (testadas sem navegador). A URL e a senha do ACS NUNCA passam por aqui: ficam no Edge. */
export type AcsHealth = "unknown" | "ok" | "error" | "stale";
export type Acs = {
  id: string; name: string; kind: string; label: string | null; enabled: boolean; settings: Record<string, unknown>;
  edge: { id: string; name: string }; created_at: string; updated_at: string;
  last_seen_at: string | null; last_ok_at: string | null; device_count: number | null; last_error_code: string | null; health: AcsHealth;
};
export type AcsList = { items: Acs[]; truncated: boolean; kinds: string[] };

export const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export const KIND_LABEL: Record<string, string> = { genieacs: "GenieACS" };
export const kindLabel = (k: string) => KIND_LABEL[k] ?? k;

/** Códigos que o Edge informa (lista fechada da API) em português. Um código que a tela não conhece vira o texto genérico, nunca o código cru como se fosse mensagem. */
export const ERROR_TEXT: Record<string, string> = {
  unreachable: "O Edge não conseguiu falar com o ACS (rede, DNS ou porta).",
  timeout: "O ACS demorou demais para responder.",
  unauthorized: "O ACS recusou o usuário e a senha do NBI configurados no Edge.",
  unexpected_status: "O ACS respondeu com um erro inesperado.",
  bad_response: "A resposta do ACS não tem o formato esperado.",
  too_large: "A resposta do ACS passou do tamanho que o Edge aceita.",
  unknown: "Falha não classificada no Edge.",
};
export const errorText = (code: string | null) => (code === null ? null : ERROR_TEXT[code] ?? ERROR_TEXT.unknown);

/** Estado lido do relato do Edge. Nunca só cor: texto e símbolo. */
export const HEALTH_TEXT: Record<AcsHealth, { label: string; symbol: string; cls: string }> = {
  unknown: { label: "Sem leitura", symbol: "○", cls: "bg-stale-soft text-muted" },
  ok: { label: "Respondendo", symbol: "●", cls: "bg-ok-soft text-ok" },
  error: { label: "Com falha", symbol: "▲", cls: "bg-danger-soft text-danger" },
  stale: { label: "Desatualizado", symbol: "◐", cls: "bg-warn-soft text-warn" },
};

/** "visto há…": o relato do Edge mais recente. Sem relato = "ainda não visto" (nunca um tempo inventado). */
export function seenText(lastSeenAt: string | null, now = Date.now()): string {
  if (!lastSeenAt) return "ainda não visto";
  const s = Math.max(0, Math.round((now - new Date(lastSeenAt).getTime()) / 1000));
  if (s < 90) return "visto agora há pouco";
  if (s < 5400) return `visto há ${Math.round(s / 60)} min`;
  if (s < 172800) return `visto há ${Math.round(s / 3600)} h`;
  return `visto há ${Math.round(s / 86400)} d`;
}

export const countText = (n: number | null) => (n === null ? "—" : `${n.toLocaleString("pt-BR")} dispositivo${n === 1 ? "" : "s"}`);

export const NAME_MIN = 2, NAME_MAX = 60, LABEL_MAX = 80;
/** Só o formato (quem decide é a API); o texto digitado nunca volta numa mensagem de erro. */
export function nameProblem(v: string): string | null {
  const t = v.trim();
  return t.length < NAME_MIN || t.length > NAME_MAX ? `O nome tem de 2 a ${NAME_MAX} caracteres.` : null;
}

export const ACS_FLASH: Record<string, string> = {
  criado: "ACS cadastrado. Copie o identificador dele para o campo nbi_cloud_id do config.json do Edge (a URL e a senha do GenieACS continuam só no Edge).",
  atualizado: "ACS atualizado.", ativado: "ACS ativado.", desativado: "ACS desativado.",
  permissao: "Seu papel não permite esta ação.",
  nome: "Já existe um ACS com esse nome neste Edge.",
  outroativo: "Este Edge já tem um ACS ativo. Desative o atual antes de ativar outro.",
  invalido: "Algum campo está fora do formato. O nome tem de 2 a 60 caracteres e o rótulo, no máximo 80.",
  edge: "O Edge escolhido não existe neste provedor.", naoexiste: "Esse ACS não existe mais neste provedor.",
  desligado: "O recurso ACS está desligado para este provedor.",
  falha: "Não foi possível concluir. Tente novamente.",
};

/** Código de falha da API de cadastro (status + detalhe) → chave de ACS_FLASH. */
export function flashFor(status: number, detail: unknown): string {
  if (status === 403) return detail === "feature_disabled" ? "desligado" : "permissao";
  if (status === 409) return detail === "edge_already_has_active_acs" ? "outroativo" : detail === "acs_name_taken" ? "nome" : "falha";
  if (status === 404) return detail === "edge not found" ? "edge" : "naoexiste";
  if (status === 422) return "invalido";
  return "falha";
}
