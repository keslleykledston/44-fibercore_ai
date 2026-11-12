// Credenciais de OLT pela tela (ADR-0045): tipos da API e textos em português. Nenhum segredo, blob ou valor digitado passa por aqui: só estados, códigos e rótulos.

export type SealKey = {
  tenant_id: string; edge_id: string; edge_name: string; state: "none" | "pending" | "confirmed"; key_id: string | null; public_key: string | null; fingerprint: string | null;
  reported_at: string | null; confirmed_at: string | null; server_time: number; max_window_seconds: number;
};
export type Delivery = { id: string; kind: "ssh_login" | "snmp_community"; status: string; code: string | null; key_id: string; expires_at: number; expires_at_iso: string; created_at: string; updated_at: string; attempts: number };

export const KIND_PT: Record<string, string> = { ssh_login: "Login e senha (SSH)", snmp_community: "Community SNMP v2c" };
export const STATUS_PT: Record<string, string> = {
  PENDING: "Aguardando o Edge", DISPATCHED: "Entregue ao Edge, aguardando a aplicação", APPLIED: "Aplicada", FAILED: "Falhou", EXPIRED: "Expirou sem ser aplicada", CANCELLED: "Cancelada",
};
/** Códigos de falha (informados pelo Edge) e de cancelamento, em português. Códigos desconhecidos viram uma frase genérica: o texto da API nunca é mostrado. */
export const CODE_PT: Record<string, string> = {
  bad_key_id: "A chave do Edge mudou desde a digitação. Confirme a nova impressão digital e envie de novo.",
  expired: "O prazo da entrega venceu antes de o Edge aplicar. Envie de novo.",
  aad_mismatch: "O Edge recusou: a entrega não é para esta OLT ou este Edge.",
  bad_signature: "O Edge recusou: assinatura da nuvem inválida (confira a chave pública da nuvem no Edge).",
  decrypt_failed: "O Edge não conseguiu abrir a entrega (chave diferente). Confirme a impressão digital e envie de novo.",
  invalid_payload: "O Edge recusou o conteúdo (formato ou tamanho dos campos).",
  stale: "O Edge já aplicou uma entrega mais nova deste tipo.",
  target_not_configured: "Esta OLT não aceita credencial remota: o administrador do Edge precisa habilitar credentials_file para ela.",
  write_failed: "O Edge não conseguiu gravar o arquivo de credenciais (permissão ou disco).",
  state_unreadable: "O Edge não conseguiu ler o próprio registro de entregas aplicadas.",
  lease_exhausted: "O Edge não respondeu a tempo em várias tentativas.",
  key_changed: "A chave do Edge mudou: a entrega foi cancelada e o conteúdo apagado.",
};
export const codeText = (c: string | null) => (c ? CODE_PT[c] ?? "Falha não identificada." : null);

/** Respostas da API/BFF ao enviar, em português (códigos estáveis; nunca o valor enviado). */
export const SEND_ERR_PT: Record<string, string> = {
  seal_key_not_confirmed: "A chave do Edge ainda não foi confirmada. Confirme a impressão digital antes de enviar.",
  key_id_mismatch: "A chave do Edge mudou. Atualize a página, confira a nova impressão digital e envie de novo.",
  seal_key_changed: "A chave do Edge mudou. Atualize a página e confira a nova impressão digital.",
  expires_at_out_of_window: "O relógio não confere com o da nuvem. Atualize a página e tente de novo.",
  too_many_pending: "Já há 5 entregas aguardando para esta OLT. Espere o Edge aplicar ou expirar.",
  delivery_id_taken: "Este envio já foi registrado. Digite de novo para fazer outro.",
  snmp_v3_unsupported: "Esta OLT está cadastrada com SNMP v3, que o Edge ainda não suporta: só community v2c.",
  forbidden: "Seu papel não permite enviar credenciais.",
  unauthorized: "Sua sessão terminou. Entre de novo.",
  invalid: "Algum campo está fora do formato.",
  too_large: "O envio passa do limite de tamanho.",
  falha: "Não foi possível enviar agora. Tente de novo.",
};

export const EDGE_ADMIN_NOTE = "O administrador do Edge precisa habilitar credentials_file para esta OLT na configuração do Edge; sem isso o Edge responde “esta OLT não aceita credencial remota”.";
