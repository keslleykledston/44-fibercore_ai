# ADR-0029: Canal de execução das consultas somente leitura da OLT (job `olt_query`)

Status: Proposed (aguarda Codex gate e aceite do responsável) | Data: 2026-10-30 | Owner: equipe | Origem: ADR-0026 item 5 (o catálogo existe e é inerte; falta o canal)

## Contexto
O ADR-0026 criou o catálogo tipado de consultas `display` da OLT (25 consultas, 4 validadas na OLT real) e deixou de propósito sem canal de execução: nada chama `RunQuery`. A OLT real tem um agente SNMP que limita a 1 requisição por segundo (cooldown de 5 min após estouro) e o guard de CLI (PR 43/44) impõe uma sessão por vez por equipamento, reserva persistida, intervalo e cooldown de 15 min e instância única por `flock`. Qualquer canal novo compete com a coleta periódica pelo mesmo equipamento e não pode enfraquecer esse limite.

## Decisão
1. **Uma operação nova, somente leitura:** `olt_query` em `OPERATIONS` (`R0`, alvo `olt`, sem escrita, sem aprovação), pelo mesmo ciclo de jobs (preview → submit → envelope assinado → Edge verifica → resultado → pós-checagem), desligada por padrão por flag do tenant e por `allowed_operations` no Edge. `HOMOLOGATED_WRITES` continua vazio e uma operação de escrita não pode ser expressa por este canal.
2. **Parâmetros no envelope ASSINADO, nunca texto de comando:** `{query_id, slot?, port?, ont?}` com `query_id` do catálogo e inteiros limitados (slot 0–17, porta 0–15, ONT-ID 0–127). A nuvem valida contra o mesmo catálogo (um teste cruza os dois lados, como já se faz com `params.go`), assina, e o Edge revalida (`Query.Render` recusa tudo fora dos limites) e só aceita IDs `Validated` ou habilitados localmente pelo operador (ADR-0026 item 2). O comando efetivo é sempre produzido pelo Edge a partir do modelo; o alvo é o `olt` do próprio Edge (nunca um endereço vindo da nuvem).
3. **Orçamento, sem enfraquecer o guard:** a consulta é executada DENTRO de uma sessão que o guard já permitiria, não ao lado dela. O Edge enfileira as consultas aprovadas e as consome na próxima janela de sessão da OLT (a mesma reserva persistida e o mesmo intervalo de 15 min da coleta), em lote de no máximo 5 consultas por sessão e 20 por hora por OLT. Quem pede vê o estado `APPROVED` até a janela abrir e recebe `EXPIRED` se ela não abrir no prazo do envelope (curto): nada é prometido em tempo real e nenhuma tentativa é repetida automaticamente. Reinício do Edge não perde nem duplica consulta (id do job como chave de idempotência; o resultado fica durável até ser reconhecido, como nos jobs atuais).
4. **A saída crua nunca sai do Edge.** O resultado é um objeto TIPADO produzido por parser da consulta (campos fechados, números e palavras de enum, tamanho máximo); consulta sem parser só pode rodar em captura local supervisionada e seu job falha com `no_parser` sem executar. Texto escolhido pelo cliente (descrição de ONT, nome) não é campo do resultado. O Edge registra localmente só categorias de erro, não saída.
5. **Sem exposição ampla:** permissão própria (`olt_query:run`, perfis N2/engenharia), uma consulta por job, `scope` limitado ao catálogo, auditoria da solicitação (quem, qual consulta, parâmetros inteiros, OLT), cota por tenant e por usuário (429) e limite do tamanho do resultado. Dado de cliente identificável não entra no resultado nem no log do job.
6. **Promoção das consultas ainda não validadas:** cada uma exige captura supervisionada na OLT real (autorização do responsável, janela combinada, uma por vez), fixture sanitizada, parser e teste de ouro; só então `Validated=true`. Esta decisão não autoriza executar nada na OLT por si só.
7. **Rollout:** primeiro apenas `olt.version` e `olt.board` (globais, validadas), depois as de PON; cada degrau com ensaio supervisionado na LAB e registro em `TEST_EVIDENCE`.

## Consequências
- Consulta sob demanda tem latência de até uma janela de sessão (15 min): é o preço de não abrir mais sessões na OLT real. O produto mostra o estado e a idade do dado, nunca um zero.
- O Edge ganha uma fila persistente de consultas e parsers por consulta; a nuvem ganha uma operação, uma permissão, uma cota e tipos de resultado.
- Fora de escopo: qualquer escrita, comando livre, SNMP sob demanda (o limite de 1 req/s continua sendo do coletor) e consultas em equipamentos sem driver validado.
- Risco residual: duas instâncias Edge contra a mesma OLT não se coordenam (regra "uma instância", `flock` por diretório de estado); o mesmo risco aceito nos PRs 51 e 52.

## Alternativas descartadas
Sessão extra fora da janela do guard (enfraquece a proteção da OLT); comando livre com validação por regex (superfície grande e já recusada no ADR-0026); devolver a saída crua para a nuvem filtrar depois (o dado sensível já teria saído do site).
