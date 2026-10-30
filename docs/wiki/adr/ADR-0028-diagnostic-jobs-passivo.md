# ADR-0028 — Diagnostic jobs passivos (SD-PR-03): evidência, achados e replay, só leitura

Status: Accepted | Data: 2026-10-30 | Owner: equipe

Relaciona-se a ADR-0025 (integração do SD-001), ADR-0024 (regras puras), ADR-0027 (R-D002), ADR-0021 (vínculos e contexto do cliente) e ao contrato `contracts/sd001`.

## Contexto
O ADR-0025 reservou `diagnostic_jobs` para o ciclo de vida do diagnóstico do pacote SD-001, distinto de `diagnostic_runs` (uma regra, síncrona). Com `cpe_state` e R-D002 existe dado real para um diagnóstico centrado no cliente, sem tocar equipamento. Testes ativos, remediação, copiloto e USP continuam bloqueados (ADR-0025, item 8).

## Decisão
1. **Recurso novo e imutável** `diagnostic_jobs` (migração 0020; a app só faz `INSERT`/`SELECT`, RLS forçada, idempotência por (tenant, usuário, `Idempotency-Key`)). `POST /v1/diagnostics/jobs` (`diagnostics:run`) e `GET /v1/diagnostics/jobs/{id}` (`incidents:read`), atrás das flags `smart_diagnostics_jobs` E `diagnostic_engine` (ambas desligadas por padrão). As duas operações foram do overlay para o contrato canônico; os esquemas compartilhados continuam no overlay (usados pelas operações ainda não implementadas) e um teste impede divergência.
2. **Só modo `passive` e só dado já retido**: ONU (estado/RX da OLT) e estado do CPE do cache do ACS (`cpe_state`). Domínios aceitos: `pon` e `wan` (os demais do contrato não têm fonte e são recusados com 422; `guided` e `service_id` ficam para o PR que os implementar). Não há tarefa assíncrona: o trabalho são leituras indexadas e termina no pedido; o recibo traz o `status` real (`complete`/`partial`/`inconclusive`), por isso o enum do recibo foi ampliado (os estados assíncronos seguem para os testes ativos).
3. **Resolução:** cliente → ONUs com associação `approved` (até 10, o excesso vira achado inconclusivo) → CPE pelo vínculo ONU↔CPE `confirmed` (ADR-0021). `cpe_id` opcional só vale se ligado a uma ONU aprovada do cliente (422 caso contrário). Cliente inexistente ou de outro tenant: 404.
4. **Regras:** R-D001 sobre a PON da ONU e R-D002 sobre o CPE ligado. As regras executadas (id, versão, ENTRADAS exatas e achados) ficam gravadas em `rule_runs`; `GET` recalcula cada uma com a mesma versão e devolve `reproducible`. Não cria `diagnostic_runs` (`run_id` é nulo; o replay é do próprio job), não abre incidente, não escreve estado, não publica evento.
5. **Montagem pura** (`app/core/diagnostic_jobs.py`, sem relógio/banco/rede, testada por propriedade e por AST): evidências com id opaco (sem serial), `status` `available`/`stale`/`inconclusive`, valor da lista permitida ou número (nunca texto livre) e `method` só quando conhecido (CPE: `genieacs_nbi`; a OLT não registra o transporte, então não se afirma). Cada achado cita evidência existente; dado antigo ou ausente vira `insufficient_evidence` (nunca veredito de saúde); hipótese de regra é `possible` (R-D002) ou `likely` (R-D001), nunca `confirmed`; só o fato que a OLT informa (ONU fora do ar) é `confirmed`, dizendo que não indica a causa. `data_quality`: `fresh`, `partial`, `stale` (todas velhas) ou `unsupported` (sem evidência); `status` segue dela.
6. **Dado pessoal:** nenhum nome, documento ou serial é gravado; só ids, palavras de enum e números. A criação é auditada com o id do cliente.

## Consequências
- O contrato de evidência fica exercitado de verdade (a resposta é validada contra o esquema do contrato nos testes).
- Categoria `WAN_AUTH` não é usada: autenticação PPPoE exigiria log de autenticação que não temos; toda hipótese da R-D002 sai como `WAN_LINK`/`possible` com texto que diz o que o CPE informa.
- Wi-Fi, LAN, internet, ERP e BNG ficam sem fonte; pedir esses domínios é 422, não um resultado vazio.
- Mudar o mapeamento de achados é mudança de comportamento: exige nota neste ADR e teste novo.
