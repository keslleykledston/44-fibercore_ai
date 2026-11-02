// Base de conhecimento (ADR-0041, PR5): referência SOMENTE LEITURA. Nada aqui é executável nem prova de suporte de um modelo/firmware.
export const SECTIONS = [
  { id: "fontes", api: "sources", label: "Fontes" },
  { id: "comandos", api: "commands", label: "Consultas documentadas" },
  { id: "runbooks", api: "runbooks", label: "Runbooks" },
  { id: "intents", api: "intents", label: "Intenções de serviço" },
  { id: "receitas", api: "recipes", label: "Receitas de tradução" },
  { id: "homologacao", api: "homologation", label: "Homologação" },
] as const;
export type SectionId = (typeof SECTIONS)[number]["id"];
export const KB_WARNING = "Documentado não é verificado: nenhum item desta base foi testado em equipamento pelo FiberCore, nenhum é executável e nenhum prova suporte de modelo ou firmware.";
export type Source = { id: string; vendor: string; family: string; title: string; url: string; authority: string; topic: string; relevant: string; caveat: string };
export type Command = { id: string; vendor: string; family: string; syntax: string; cli_context: string; purpose: string; source_ids: string[]; confidence: string; verification: string; risk: string; notes: string; executable: false };
export type Recipe = { vendor: string; family: string; source_ids: string[]; status: string; steps: string[]; omitted_change_steps: number; examples: string[]; restrictions: string[] };
export type Intent = { id: string; label: string; onu_mode: string; vlan_mode: string; parameters: string[]; required_tests: string[] };
export type MatrixRow = Record<string, string>;
export const RECIPE_STATUS_LABEL: Record<string, string> = {
  documented_example_not_homologated: "Exemplo documentado, não homologado",
  research_only: "Só pesquisa",
  inherited_in_fibercore_verify_local: "Já existe no FiberCore; verificar no local",
};
export const RISK_LABEL: Record<string, string> = { low: "Risco baixo", medium: "Risco médio", high: "Risco alto" };
/** Só links https de fontes (a API já recusa o resto); defesa em profundidade no cliente. */
export const safeUrl = (u: string) => (/^https:\/\/[^\s]+$/.test(u) ? u : null);
