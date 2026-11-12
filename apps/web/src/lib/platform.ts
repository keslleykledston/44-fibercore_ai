/** Organizações da plataforma (ADR-0046 D1): tipos, textos em português e o mapa de erros. Funções puras (testadas sem navegador); nada aqui toca a rede. */
export type PlatformStatus = { operator: boolean; mfa_recent: boolean };
export type PlatformOrg = {
  id: string; name: string; status: string; created_at: string; edges: number; olts: number; onus: number;
  created_by: string | null; created_via: "screen" | "cli"; invite_state: "pending" | "accepted" | "expired" | "revoked" | null; api_trail: boolean | null;
};
export type PlatformOrgList = { total: number; next: { before_at: string; before_id: string } | null; items: PlatformOrg[] };
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
};
export const ORG_FLASH: Record<string, string> = { mfaok: "Segundo fator confirmado.", oculto: "Link do convite ocultado." };

/** Erro da API → código curto da tela. Nunca repassa texto da API (só um código estável). */
export function orgError(status: number, json: unknown): string {
  const detail = (json as { detail?: unknown } | null)?.detail;
  if (status === 403) return detail === "mfa_recent_required" ? "mfa" : "permissao";
  if (status === 409) return detail === "organization_name_taken" ? "duplicada" : "falha";
  if (status === 429) return "limite";
  if (status === 422) {
    if (detail === "organization_name_invalid") return "nome";
    if (detail === "organization_email_invalid") return "email";
    if (detail === "organization_admin_name_invalid") return "admin";
    if (Array.isArray(detail)) {
      const field = (detail[0] as { loc?: unknown[] } | undefined)?.loc?.[1];
      return field === "name" ? "nome" : field === "admin_email" ? "email" : field === "admin_name" ? "admin" : "invalido";
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
export const inviteUrl = (base: string, token: string) => `${base.replace(/\/+$/, "")}/convite/${token}`;

/** `?antes=<instante>~<id>` da tela → consulta da API. Só passa instante ISO e UUID no formato certo; qualquer outra coisa é ignorada (volta à primeira página). */
const ISO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|[+-]\d{2}:\d{2})$/;
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export function cursorQuery(raw: string): string {
  const [at, id] = raw.split("~");
  if (!at || !id || !ISO.test(at) || !UUID_RE.test(id)) return "";
  return new URLSearchParams({ before_at: at, before_id: id }).toString();
}
