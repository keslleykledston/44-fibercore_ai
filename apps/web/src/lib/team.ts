import type { TeamActivityItem } from "./types";

/** Mensagens fixas da tela de equipe para os códigos estáveis da API (nunca texto livre vindo da API). */
export const TEAM_ERROR: Record<string, string> = {
  role_cannot_grant: "Seu papel não pode gerenciar pessoas.",
  role_not_assignable: "Seu papel não pode dar esta função.",
  target_role_protected: "Só um Administrador mexe com Administrador e Gestor de acesso.",
  cannot_remove_self: "Você não pode remover a si mesmo.",
  use_change_password: "Para a sua própria senha use Conta › Segurança da conta.",
  member_not_found: "Esta pessoa não faz mais parte da equipe.",
  invite_not_found: "Este convite não existe mais.",
  invite_not_open: "Este convite já foi usado, cancelado ou substituído.",
  already_member: "Esta pessoa já faz parte da equipe.",
  last_isp_admin: "Não dá para tirar o último Administrador. Nomeie outro primeiro.",
  account_shared: "Esta conta também pertence a outro provedor, então só a própria pessoa pode trocar a senha (Conta › Segurança da conta).",
  email_invalid: "Digite um e-mail válido.",
  name_invalid: "O nome precisa ter de 1 a 100 caracteres.",
  reason_required: "Escreva o motivo (3 a 200 caracteres).",
  conflict_retry: "Outra mudança aconteceu ao mesmo tempo. Tente de novo.",
  mfa_recent_required: "Confirme o segundo fator para continuar.",
  bad_request: "Confira os dados informados.",
  session: "Sua sessão expirou. Recarregue a página e entre de novo.",
  forbidden: "Seu papel não permite esta ação.",
  unavailable: "Serviço indisponível. Tente em instantes.",
  failed: "Falha inesperada. Tente em instantes.",
};

/** Mensagens da página pública de convite. */
export const INVITE_ERROR: Record<string, string> = {
  password_short: "A senha precisa ter pelo menos 12 caracteres.",
  password_weak: "Esta senha é fácil demais de adivinhar. Use uma frase longa, sem o seu nome nem o seu e-mail.",
  password_long: "A senha é longa demais (máximo 256 caracteres).",
  invalid_credentials: "A senha atual não confere.",
  throttled: "Muitas tentativas. Aguarde 15 minutos e tente de novo.",
  invite_used: "Este convite já foi usado.",
  invite_revoked: "Este convite foi cancelado.",
  invite_expired: "Este convite venceu.",
  invite_invalid: "Este link não é válido.",
  account_inactive: "Esta conta está desativada. Fale com a pessoa que convidou você.",
  already_member: "Você já faz parte desta equipe.",
  reset_not_allowed: "Não foi possível trocar a senha por este link. Peça um novo.",
  details_required: "Preencha o nome e a senha.",
  mismatch: "As duas senhas não são iguais.",
  unavailable: "Serviço indisponível. Tente em instantes.",
  failed: "Falha inesperada. Tente em instantes.",
};

export const initials = (name: string) => name.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]!.toUpperCase()).join("") || "?";

/** "há 2 dias", "há 5 min" — sem biblioteca. */
export function ago(iso: string, now = Date.now()): string {
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (s < 60) return "agora há pouco";
  if (s < 3600) return `há ${Math.floor(s / 60)} min`;
  if (s < 86400) return `há ${Math.floor(s / 3600)} h`;
  const d = Math.floor(s / 86400);
  return `há ${d} ${d === 1 ? "dia" : "dias"}`;
}

export const when = (iso: string) => new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short", timeZone: "America/Sao_Paulo" });

/** O link de convite é montado no navegador, com a origem que a pessoa está usando. */
export const inviteLink = (origin: string, token: string) => `${origin}/convite/${token}`;

/** Uma frase por fato da atividade. Texto da pessoa (motivo) é mostrado como texto, nunca como marcação. */
export function sentence(i: TeamActivityItem): string {
  const who = i.actor ?? "Alguém";
  const target = i.target ?? i.email ?? "uma pessoa";
  const why = i.reason ? ` Motivo: ${i.reason}.` : "";
  switch (i.kind) {
    case "member.role_change": return `${who} mudou a função de ${target}${i.from_label ? ` de ${i.from_label}` : ""}${i.to_label ? ` para ${i.to_label}` : ""}.${why}`;
    case "member.invite": return `${who} convidou ${i.email ?? "uma pessoa"}${i.to_label ? ` como ${i.to_label}` : ""}.`;
    case "member.invite_accepted": return `${target} aceitou o convite${i.to_label ? ` e entrou como ${i.to_label}` : ""}.`;
    case "member.invite_revoke": return `${who} cancelou um convite.`;
    case "member.remove": return `${who} removeu ${target} da equipe.${why}`;
    case "member.password_reset_link": return `${who} gerou um link para ${target} trocar a senha.`;
    case "member.password_reset_done": return `${target} trocou a senha pelo link.`;
    case "member.mfa_reset": return `${who} redefiniu a verificação em duas etapas de ${target}.`;
    case "account.password_change": return `${who} trocou a própria senha.`;
    case "platform.delegation_grant": return `${who} deu acesso temporário ao suporte da plataforma${i.hours ? ` por ${i.hours} h` : ""}.${why}`;
    case "platform.delegation_revoke": return `${who} encerrou o acesso temporário do suporte da plataforma.`;
    case "bench.authorize": return `${who} autorizou uma manobra de bancada.`;
    case "bench.authorize_revoke": return `${who} encerrou uma autorização de bancada.`;
    default: return `${who}: ${i.kind}`;
  }
}

export const ACTIVITY_FILTERS: { id: string; label: string; kinds: string[] }[] = [
  { id: "", label: "Tudo", kinds: [] },
  { id: "pessoas", label: "Pessoas e funções", kinds: ["member.role_change", "member.invite", "member.invite_accepted", "member.invite_revoke", "member.remove"] },
  { id: "senhas", label: "Senhas e verificação", kinds: ["member.password_reset_link", "member.password_reset_done", "member.mfa_reset", "account.password_change"] },
  { id: "plataforma", label: "Suporte e bancada", kinds: ["platform.delegation_grant", "platform.delegation_revoke", "bench.authorize", "bench.authorize_revoke"] },
];
