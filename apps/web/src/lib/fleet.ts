/** Fleet Manager (ADR-0041, PR2): tipos da API e rótulos. A credencial NUNCA é digitada aqui: só o NOME do segredo que o Edge guarda localmente. */
export type FleetOlt = {
  id: string; name: string; vendor: string; model: string | null; firmware: string | null; support_level: string; observed_at: string | null;
  has_credential_ref: boolean; mgmt_address_masked: string | null; snmp_version: string | null; label: string | null; pop: { id: string; name: string } | null; registered: boolean; registered_at: string | null;
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
export const CRED_HELP = "O NOME do segredo guardado no Edge (letras minúsculas, números, . _ -). Nunca digite senha, community ou chave aqui: a entrada segura de login, senha e community pela tela é uma etapa futura (hoje ficam só no Edge).";

/** Teste de conexão (parte B): leitura somente leitura da identidade da OLT pelo Edge, com orçamento de 1 por 15 min e 4 por hora por OLT. */
export type ConnectionTests = {
  items: { id: string; outcome: "submitted" | "cached"; requested_at: string; job_status: string | null }[];
  latest: { identity: { vendor: string; model: string; firmware: string; patch: string; uptime_seconds: number; matches_collected: boolean | null }; asked_at: string; age_seconds: number; stale: boolean } | null;
  budget: { used_last_hour: number; max_per_hour: number; gap_minutes: number; wait_seconds: number };
};
export const JOB_LABEL: Record<string, string> = {
  SUCCEEDED: "Concluído", FAILED: "Falhou", EXPIRED: "Expirou sem resposta", UNKNOWN: "Resultado incerto", CANCELLED: "Cancelado",
  APPROVED: "Aguardando o Edge", DISPATCHED: "Aguardando o Edge", ACCEPTED: "Aguardando o Edge", SUBMITTED: "Aguardando o Edge", PENDING_APPROVAL: "Aguardando o Edge",
};
export const uptimeText = (s: number) => `${Math.floor(s / 86400)} d ${Math.floor((s % 86400) / 3600)} h ${Math.floor((s % 3600) / 60)} min`;
Object.assign(FLEET_FLASH, {
  testepedido: "Teste pedido ao Edge. A leitura roda na próxima janela de coleta (pode levar alguns minutos): atualize a página para ver o resultado.",
  testecache: "Já há uma identidade recente guardada: nenhuma consulta foi feita à OLT.",
  orcamento: "Limite de testes atingido: no máximo 1 teste a cada 15 minutos e 4 por hora por OLT. Veja quando o próximo é permitido no cartão do teste.",
  consulta: "O teste não está disponível agora (recurso desligado, canal do Edge ausente ou consulta retirada da liberação).",
});

export const SNMP_VERSIONS: [string, string][] = [["v2c", "SNMP v2c"], ["v3", "SNMP v3"]];
export const ADDRESS_HELP = "Endereço de gerência da OLT (IPv4 ou IPv6, sem porta nem máscara). Depois de salvo só aparece mascarado. É apenas cadastro: o Edge usa o endereço da configuração dele.";
Object.assign(FLEET_FLASH, {
  oltcomteste: "OLT cadastrada e teste de conexão pedido ao Edge. A leitura roda na próxima janela de coleta (pode levar alguns minutos): atualize a página para ver o resultado. O Edge precisa ter esta OLT na configuração dele (mesmo nome).",
  oltcomtestecache: "OLT cadastrada. Já havia uma identidade recente guardada: nenhuma consulta foi feita à OLT.",
  oltsemteste: "OLT cadastrada, mas o teste de conexão não pôde ser pedido agora (recurso desligado, canal do Edge ausente ou limite de testes). Use o botão Testar conexão abaixo quando disponível.",
});

/** Site (POP) digitado no cadastro: casa pelo nome, sem diferenciar maiúsculas, com um site já existente; se não casar, oferece criar. Função pura (testada sem navegador). */
export type PopChoice = { id: string | null; typed: string; create: boolean; matches: { id: string; name: string }[] };
export function popChoice(text: string, pops: { id: string; name: string }[]): PopChoice {
  const typed = text.trim().replace(/\s+/g, " ");
  const key = typed.toLocaleLowerCase("pt-BR");
  const exact = key ? pops.find((p) => p.name.trim().toLocaleLowerCase("pt-BR") === key) : undefined;
  const matches = key ? pops.filter((p) => p.name.toLocaleLowerCase("pt-BR").includes(key)) : pops;
  return { id: exact?.id ?? null, typed, create: key.length >= 2 && !exact, matches };
}
