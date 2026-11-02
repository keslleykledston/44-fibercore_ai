/** Profile Studio (ADR-0040): tipos da API e rótulos em português. Tudo aqui é somente leitura/rascunho: nada vai para a OLT. */
export type Snapshot = {
  id: string; olt_id: string; native_type: string; native_key: string; technology: string; vendor: string; model: string; firmware: string; pon_card: string;
  observed_at: string; freshness: "fresh" | "stale" | "unknown"; completeness: "complete" | "partial" | "unknown"; reference_count: number | null;
  settings: Record<string, unknown>; unknown_fields: string[]; source: string; authoritative: boolean; has_evidence?: boolean; evidence?: string | null;
};
export type ProfileList = { olt_id: string; olt_name: string; driver_read_certified: boolean; items: Snapshot[]; fresh_window_hours: number };
export type Draft = {
  id: string; name: string; source_snapshot_id: string | null; scope: { technology: string; vendor: string; model: string; firmware: string; pon_card: string };
  profile_kind: string; target_olt_ids: string[]; desired: Record<string, unknown>; vendor_extensions: Record<string, unknown>; strategy: string | null; reason: string;
  row_version: number; updated_at: string;
};
export type Compare = {
  snapshot_id: string; olt_id: string; driver_read_certified: boolean; snapshot_freshness: string; snapshot_completeness: string; diff: Record<string, string>;
  counts: Record<string, number>; equivalent: boolean; blockers: string[]; issues: { field: string; code: string }[]; draft_row_version: number;
};
export type Plan = { olt_id: string; strategy: string; reason: string; diff: Record<string, string>; changed_fields: string[]; reference_count: number | null; writes: number; plan_hash: string };
export type DryRun = { run_id: string; draft_id: string; draft_row_version: number; expires_at: string; expired?: boolean; reproducible?: boolean; writes: number; plans: Plan[]; issues: { field: string; code: string }[]; executable: boolean };

export const FIELD_LABEL: Record<string, string> = {
  dba_type: "Tipo de DBA", fixed_kbps: "Banda fixa (kbps)", assured_kbps: "Banda assegurada (kbps)", maximum_kbps: "Banda máxima (kbps)", tconts: "T-CONTs", gems: "GEM ports",
  customer_vlan: "VLAN do cliente", service_vlan: "VLAN de serviço", tagging: "Marcação (tag)", ethernet_ports: "Portas Ethernet", shaping_owner: "Quem limita a banda", multicast: "Multicast",
  description: "Descrição",
};
export const SCALAR_NUM = ["fixed_kbps", "assured_kbps", "maximum_kbps", "customer_vlan", "service_vlan"] as const;
export const LIST_FIELDS = ["tconts", "gems", "ethernet_ports"] as const;
export const TAGGING = ["tagged", "untagged", "translation", "qinq", "unknown"] as const;
export const SHAPING = ["bng", "olt", "cpe", "none", "unknown"] as const;

export const DIFF_LABEL: Record<string, string> = {
  EQUAL: "Igual", CHANGE: "Muda", ADD: "Acrescenta", REMOVE: "Remove", NOT_OBSERVABLE: "Não observado", UNSUPPORTED: "Sem leitura certificada", CONFLICT: "Conflito",
};
export const STRATEGY_LABEL: Record<string, string> = {
  reuse_exact: "Reutilizar o perfil idêntico", adopt_reference: "Adotar a referência existente", clone_new_revision: "Clonar como nova revisão", plan_migration: "Planejar migração", blocked: "Bloqueado",
};
export const BLOCKER_LABEL: Record<string, string> = {
  read_not_certified: "A leitura de perfis ainda não está certificada para este modelo/firmware da OLT.",
  snapshot_not_authoritative: "O instantâneo foi importado à mão (ou é fixture): não vale como observação da OLT.",
  stale_or_unknown_snapshot: "O instantâneo está velho ou sem data confiável.",
  incomplete_observation: "A leitura da OLT veio incompleta.",
  incomplete_or_conflicting_observation: "Há campos não observados, sem leitura certificada ou em conflito.",
};
export const SOURCE_LABEL: Record<string, string> = { edge_read: "Lido da OLT pelo Edge", manual_import: "Importado à mão", fixture: "Fixture de teste" };
export const FRESH_LABEL: Record<string, string> = { fresh: "Atual", stale: "Defasado", unknown: "Sem data confiável" };
export const ISSUE_LABEL: Record<string, string> = {
  type: "tipo inválido", range: "fora da faixa", enum: "valor não permitido", forbidden_key: "campo proibido (comando/segredo)", unknown_field: "campo desconhecido",
  duplicate_index: "índice repetido", gem_without_tcont: "GEM aponta para T-CONT inexistente", qos_min_exceeds_max: "assegurada maior que a máxima",
  driver_capability_unsupported: "o driver não certifica este campo", extension_not_approved: "extensão do fabricante não aprovada", invalid: "inválido",
};
export const REASON_LABEL: Record<string, string> = {
  target_out_of_scope: "A OLT é de outro fabricante/modelo/firmware que o rascunho.", not_equivalent: "Nenhum perfil observado é equivalente.", source_changed: "O perfil de origem mudou na OLT.",
  draft_only_needs_approval_to_deploy: "Fica só como rascunho: aplicar exigiria aprovação separada (não existe nesta versão).",
  no_device_change: "Já existe um perfil equivalente: nenhuma mudança na OLT.", no_observation: "Não há perfil observado nesta OLT para comparar.",
  target_drift: "O perfil mudou na OLT depois da observação.", references_unknown: "Não se sabe quantas ONUs usam o perfil: bloqueado.",
  separate_approval_and_canary_required: "Migração exige aprovação separada e piloto em poucas ONUs (não existe nesta versão).",
  cross_tenant_or_target: "A observação não pertence a este provedor/OLT: ignorada.", invalid_draft: "O rascunho tem campos inválidos para esta OLT.", invalid_strategy: "Estratégia pedida não é válida.",
  read_not_certified: "A leitura de perfis não está certificada para esta OLT.", snapshot_not_authoritative: "O instantâneo não vale como leitura da OLT.",
  stale_or_unknown_snapshot: "O instantâneo está velho ou sem data confiável.", incomplete_observation: "A leitura da OLT veio incompleta.", incomplete_or_conflicting_observation: "Há campos não observados ou em conflito.",
};
export const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export const issueText = (i: { field: string; code: string }) => `${FIELD_LABEL[i.field] ?? i.field}: ${ISSUE_LABEL[i.code] ?? i.code}`;

/** Lê o JSON de uma lista/objeto digitado: só aceita o tipo esperado; erro devolve `undefined` (a tela mostra mensagem fixa, nunca o texto do parser). */
export function parseJson(raw: string, kind: "object" | "array"): unknown | undefined {
  try {
    const v = JSON.parse(raw);
    if (kind === "array" ? Array.isArray(v) : v !== null && typeof v === "object" && !Array.isArray(v)) return v;
  } catch { /* texto inválido */ }
  return undefined;
}
