export const ROLE_LABEL: Record<string, string> = {
  isp_admin: "Administrador do provedor", access_manager: "Gestor de Acesso", engineer: "Engenheiro", noc_n2: "NOC nível 2", noc_n1: "NOC nível 1",
  support: "Atendimento", auditor: "Auditor", platform_support: "Suporte da plataforma (delegado)", edge_agent: "Agente Edge (conta de serviço)",
};
export const roleLabel = (r: string) => ROLE_LABEL[r] ?? r;

export const RISK: Record<string, { label: string; hint: string }> = {
  R0: { label: "Leitura", hint: "Ver dados operacionais" },
  R1: { label: "Dado sensível", hint: "Ver dado pessoal ou sensível, ou importar" },
  R2: { label: "Ação reversível", hint: "Agir sobre algo que dá para desfazer" },
  R3: { label: "Ação crítica", hint: "Irreversível ou de segurança; exige cuidado e, em breve, MFA recente" },
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
