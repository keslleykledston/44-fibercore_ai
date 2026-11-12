// Rascunho do ENDEREÇO digitado no cadastro, só EM MEMÓRIA do módulo (sobrevive à navegação do lado do cliente, nunca a um recarregamento): nunca localStorage, sessionStorage, cookie, URL ou log.
// A nuvem devolve o endereço só mascarado; o passo "entregar a conexão" precisa do endereço inteiro para selar, então o cadastro o deixa aqui e a tela do passo o consome.
const drafts = new Map<string, string>();

export function setDraftAddress(oltId: string, address: string): void {
  drafts.clear();   // no máximo um rascunho por vez
  drafts.set(oltId, address.trim());
}
export function peekDraftAddress(oltId: string): string | null {
  return drafts.get(oltId) ?? null;
}
export function clearDraftAddress(oltId?: string): void {
  if (oltId === undefined) drafts.clear(); else drafts.delete(oltId);
}
