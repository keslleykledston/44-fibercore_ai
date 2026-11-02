/** Fleet Manager (ADR-0041, PR2): tipos da API e rótulos. A credencial NUNCA é digitada aqui: só o NOME do segredo que o Edge guarda localmente. */
export type FleetOlt = {
  id: string; name: string; vendor: string; model: string | null; firmware: string | null; support_level: string; observed_at: string | null;
  has_credential_ref: boolean; label: string | null; pop: { id: string; name: string } | null; registered: boolean; registered_at: string | null;
  edge: { id: string; name: string }; edge_last_heartbeat_at: string | null; onu_count: number; collected: boolean;
};
export type Pop = { id: string; name: string; code: string | null; note: string | null; created_at: string; olts: number | null };
export const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export const FLEET_VENDORS: [string, string][] = [["huawei", "Huawei"], ["datacom", "Datacom"], ["zte", "ZTE"], ["fiberhome", "FiberHome"], ["intelbras", "Intelbras"], ["vsol", "V-SOL"], ["ubiquiti", "Ubiquiti"], ["parks", "Parks"]];
export const FLEET_FLASH: Record<string, string> = {
  olt: "OLT cadastrada. Ela ainda não foi lida: o Edge precisa ter esta OLT na configuração dele (mesmo nome) para a primeira coleta.",
  oltatualizada: "OLT atualizada.", pop: "POP criado.", popatualizado: "POP atualizado.",
  permissao: "Seu papel não permite esta ação.", nome: "Já existe uma OLT (ou POP) com esse nome.", invalido: "Algum campo está fora do formato. Confira os textos de ajuda de cada campo.",
  edge: "O Edge escolhido não existe neste provedor.", popinexistente: "O POP escolhido não existe neste provedor.", desligado: "O recurso Frota de OLTs está desligado para este provedor.",
  falha: "Não foi possível concluir. Tente novamente.",
};
export const CRED_HELP = "O NOME do segredo guardado no Edge (letras minúsculas, números, . _ -). Nunca digite senha, chave ou endereço aqui.";
