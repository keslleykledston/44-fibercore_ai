# ADR-0035: ONU Quick Inspector — painel lateral de resumo da ONU (UX 2.2)

Status: Accepted (flag desligada) | Data: 2026-10-31 | Origem: handoff "ONU Quick Inspector v2.2" do responsável; mapa em `docs/addenda/v2.2-quick-inspector/GAP_E_PLANO.md`.

## Decisão
1. **Sem endpoint, tabela ou serviço novo.** O BFF `GET /bff/onus/{id}/quick` compõe no servidor as rotas existentes `GET /v1/onus/{id}` e `GET /v1/onus/{id}/customer` (RBAC/RLS/auditoria da API intactos). Uma ONU por clique: sem N+1. Só leitura.
2. **Fontes separadas.** `pon` vem da OLT (estado + frescor da coleta); `acs` vem da observação do CPE vinculado e confirmado; um não deriva do outro. Dado velho não fica verde nem é apresentado como atual ("PON: dados defasados"); sem observação é "desconhecido". Sem contato com o ACS nunca é "ONU offline".
3. **Potência.** `null` é "RX não disponível" (nunca 0 dBm); sem limiar homologado a severidade é sempre `unknown` (sem cor).
4. **Cliente.** Nome só com associação aprovada por uma pessoa; sugestão não mostra nome; 403 = restrito; falha do cliente não derruba o resumo. O acesso continua auditado pela rota do assinante.
5. **Layout.** ≥1024 px painel direito NÃO modal (≥1440 px a lista cede 400 px); abaixo, a gaveta modal existente. Esc fecha (e devolve o foco à linha); clicar na mesma ONU não fecha; trocar de ONU cancela o pedido anterior e nunca mostra o resumo anterior.
6. **Miniatura genérica** compartilhada (`DeviceThumbnail`): sem asset de fabricante (nenhum template homologado); os pontos de luz são PON/ACS, rotulados como não sendo LEDs reais.
7. **Flag `onu_quick_inspector`** por tenant, desligada no código; desligada, o resumo antigo permanece idêntico (verificado em e2e). O CTA "Investigar" não é renderizado (não há fluxo real).

## Consequências
- `app.spec.ts` (demo com a flag ligada) passou a esperar o painel novo; o resumo antigo só é exercitado quando a flag está desligada.
- Os estados `medium/conflict` de associação e `ACS indisponível/unsupported` do handoff não existem no modelo atual e só entram quando houver dado para eles.
- A captura real da ajuda é feita quando a flag for ligada num ambiente (rascunho `rede/resumo-da-onu`).
