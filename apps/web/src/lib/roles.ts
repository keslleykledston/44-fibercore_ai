export const ROLE_LABEL: Record<string, string> = {
  isp_admin: "Administrador do provedor", access_manager: "Gestor de Acesso", engineer: "Engenheiro", noc_n2: "NOC nível 2", noc_n1: "NOC nível 1",
  support: "Atendimento", auditor: "Auditor", platform_support: "Suporte da plataforma (delegado)", edge_agent: "Agente Edge (conta de serviço)",
};
export const roleLabel = (r: string) => ROLE_LABEL[r] ?? r;

export const RISK: Record<string, { label: string; hint: string }> = {
  R0: { label: "Leitura", hint: "Ver dados operacionais" },
  R1: { label: "Dado sensível", hint: "Ver dado pessoal ou sensível, ou importar" },
  R2: { label: "Ação reversível", hint: "Agir sobre algo que dá para desfazer" },
  R3: { label: "Ação crítica", hint: "Irreversível ou de segurança; exige cuidado e, quando ativado, MFA confirmado há menos de 10 minutos" },
};

/** Mensagens fixas do painel para os códigos que a API devolve ao trocar um papel (nunca texto livre vindo da API). */
export const ROLE_CHANGE_ERROR: Record<string, string> = {
  cannot_change_own_role: "Você não pode alterar o seu próprio papel.",
  role_cannot_grant: "Seu papel não pode atribuir papéis.",
  role_not_assignable: "Seu papel não pode atribuir este papel.",
  target_role_protected: "Só um Administrador do provedor altera quem é Administrador, Gestor de Acesso ou suporte da plataforma.",
  role_unchanged: "A pessoa já tem este papel.",
  last_isp_admin: "Não dá para tirar o último Administrador do provedor. Nomeie outro primeiro.",
  conflict_retry: "Outra mudança aconteceu ao mesmo tempo. Tente de novo.",
  not_found: "Esta pessoa não faz mais parte do workspace.",
  bad_request: "Escolha o papel e escreva o motivo (3 a 200 caracteres).",
  session: "Sua sessão expirou. Recarregue a página e entre de novo.",
  unavailable: "Serviço indisponível. Tente em instantes.",
  forbidden: "Seu papel não permite esta ação.",
  failed: "Falha inesperada. Tente em instantes.",
};

/** Mensagens fixas da confirmação do segundo fator. */
export const STEP_UP_ERROR: Record<string, string> = {
  invalid: "Código inválido ou já usado. Use o próximo código do autenticador.",
  throttled: "Muitas tentativas. Aguarde alguns minutos.",
  not_enrolled: "Esta ação exige MFA. Ative o MFA em Conta → Segurança e tente de novo.",
  session: "Sua sessão expirou. Recarregue a página e entre de novo.",
  bad_request: "Digite o código de 6 dígitos (ou um código de recuperação).",
  failed: "Falha inesperada. Tente em instantes.",
};

/** Mensagens fixas do acesso temporário do suporte da plataforma. */
export const DELEGATION_ERROR: Record<string, string> = {
  operator_not_found: "Não existe um operador da plataforma com este e-mail. Peça à plataforma para confirmar o e-mail do operador.",
  already_member: "Esta pessoa já é membro do workspace: não precisa de acesso temporário.",
  cannot_delegate_to_self: "Você não pode conceder o acesso a si mesmo.",
  not_found: "Este acesso não existe mais.",
  not_active: "Este acesso já terminou.",
  bad_request: "Informe o e-mail, o motivo (10 a 300 caracteres) e o prazo (1 a 8 horas).",
  session: "Sua sessão expirou. Recarregue a página e entre de novo.",
  forbidden: "Seu papel não permite esta ação.",
  failed: "Falha inesperada. Tente em instantes.",
};
