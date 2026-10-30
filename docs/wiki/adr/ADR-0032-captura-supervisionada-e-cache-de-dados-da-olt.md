# ADR-0032: Captura supervisionada das demais consultas da OLT e banco de dados local (cache + rotinas) para não repetir consultas caras

Status: Proposed (aguarda o Codex; a captura de cada lote exige a autorização já dada pelo responsável em 2026-10-31 para "prosseguir" com a promoção das consultas, uma janela por lote) | Data: 2026-10-31 | Owner: equipe | Origem: pedido do responsável ("planeje e organize a captura das demais consultas, coletando os dados num banco local para não precisar de consultas caras e pesadas") + ADR-0026/0029.

## Contexto
- Só `olt.version` e `olt.board` (e as de PON usadas pela coleta) são validadas. As outras 21 do catálogo estão recusadas até uma captura supervisionada (OLT_QUERY_CATALOG.md).
- A OLT real é um recurso frágil e compartilhado: o CLI responde ~1 comando/s, a coleta periódica já gasta ~190 s a cada 15 min (775 ONUs, 32 PONs), o guard só permite UMA sessão por vez e o agente SNMP é do monitoramento do provedor. Cada consulta nova custa tempo dessa sessão.
- Hoje cada pedido de consulta vira um job que espera a próxima janela (até ~18 min) e repete o trabalho no equipamento mesmo que outra pessoa tenha pedido o mesmo minutos antes.

## Decisão

### 1. Princípio: perguntar à OLT o mínimo; guardar tudo o que já foi perguntado
- **Cache primeiro.** Todo resultado TIPADO de consulta validada é gravado no banco da plataforma (`olt_query_latest`: último valor por OLT + consulta + parâmetros, com `observed_at`, `received_at`, `source`). Um pedido de consulta só vira job se não houver valor mais novo que o **TTL da consulta** (tabela abaixo); caso contrário a API responde na hora `outcome: "cached"` com a idade do dado. Forçar atualização (`refresh`) é permitido, mas com cota própria (3 por hora por OLT), nunca mais barato que o job de hoje.
- **Rotinas leves em vez de consultas pesadas sob demanda.** O Edge executa, DENTRO da sessão da coleta (sem login extra), um pequeno conjunto de consultas baratas com cadência própria e envia o resultado tipado à nuvem. O que muda pouco (versão, relógio) é lido raramente; o que varia (alarmes, temperatura) em cadência moderada; o que é caro por ONU nunca é rotina.
- **Em lote, nunca por ONU.** Dado de ONU vem do que a coleta já lê por PON (`ont info … all`, `optical-info … all`). Consultas `onu.*` ficam só para diagnóstico pontual de UMA ONU, com cache de 15 min; uma tela nunca dispara `onu.*` para uma lista.
- **Séries temporais** (temperatura, CPU/memória por placa, contagem de alarmes) vão para `olt_metric_samples` (append, retenção 400 dias, mesma rotina de poda do histórico de ONUs); o resto é "último valor" mais, quando faz sentido, uma lista de eventos com marca-d'água.
- Nada disto muda o ADR-0029: catálogo fechado, somente leitura, resultado tipado (saída crua nunca sai do Edge), arrendamento e época, cota, janela da coleta. O cache só reduz quantas vezes o equipamento é perguntado.

### 2. Plano por consulta (ordem de captura = ordem de valor/risco)
`cmds` = comandos do CLI por execução; `custo` e `bytes` serão MEDIDOS na captura (a captura registra duração e tamanho; nada é estimado como fato).

| Lote | Consulta | cmds | Uso | Destino do dado | TTL / cadência da rotina |
|---|---|---|---|---|---|
| 1 | `olt.time` | 1 | desvio do relógio da OLT (afeta o horário de queda `olt_reported`) | último valor + desvio calculado | rotina 1×/h |
| 1 | `olt.sync` | 1 | estado de sincronismo das controladoras | último valor | rotina 1×/h |
| 1 | `olt.temperature` | 1 | temperatura | série | rotina 1×/h |
| 1 | `olt.alarm.active` | 1 | alarmes ativos (NOC) | último valor + série de contagem | rotina a cada coleta se barata, senão 1×/h |
| 1 | `olt.autofind` | 1 | ONTs detectadas e não confirmadas (provisionamento) | último valor | rotina 1×/h |
| 2 | `slot.cpu`, `slot.mem` | 1 por placa em uso (3) | saúde das placas | série | rotina 1×/h |
| 2 | `slot.board` | 1 por placa (3) | detalhe de placa | último valor | sob demanda, TTL 1 h |
| 3 | `pon.ont.summary` | 1 por PON | contagem por PON (alternativa BARATA a `info all`) | último valor | sob demanda, TTL 15 min |
| 3 | `pon.port.state`, `pon.port.info` | 1 por PON | estado/óptica da porta PON | último valor/série | rotina 1×/h para as PONs com incidente; senão sob demanda |
| 3 | `pon.ont.autofind` | 1 por PON | detectadas por PON | último valor | sob demanda, TTL 15 min |
| 4 | `onu.info`, `onu.optical`, `onu.alarm`, `onu.version`, `onu.capability`, `onu.eth` | 1 cada | diagnóstico pontual de UMA ONU | último valor por ONU | só sob demanda, TTL 15 min; NUNCA em rotina nem em lote |
| 5 | `olt.alarm.history`, `olt.event.history` | 1 cada, saída grande/paginada | histórico para auditoria | lista com marca-d'água | só sob demanda, TTL 1 h; só se a captura provar que cabe sem paginação ou com limite |

Fora do catálogo continuam: uplink/serviço/MAC, tráfego/estatísticas (variam por placa, saída grande) e qualquer escrita.

### 3. Como a captura é feita (supervisionada, sem login extra, sem dado de cliente)
- **Modo captura no Edge** (`olt_capture` na configuração, desligado por padrão): lista fechada de `{query_id, parâmetros}` que o Edge executa UMA vez cada, na sessão CLI da próxima coleta, depois dos comandos dela e das consultas sob demanda, no máximo 3 por sessão. Cada uma grava a saída crua num arquivo 0600 em `captures/` ao lado da fila do Edge (limite 256 KiB; mais que isso corta e marca), com duração, bytes e se houve paginação ou erro. **A saída crua não vai à nuvem, ao repositório, à Lovable nem ao ai-memory.** Depois de executada, a entrada sai da lista (não repete); qualquer erro do equipamento, paginação ou resposta fora do esperado interrompe o lote e deixa o resto para outra janela.
- **Alvos seguros:** consultas globais e de placa não trazem ONU de cliente (as de alarme/evento/autofind podem trazer seriais: sanitizar). Consultas de PON e de ONU usam SOMENTE a PON e a ONU de bancada (`0/0/14`, ONT-ID 10), nunca uma de produção.
- **Do arquivo ao parser:** o responsável (ou eu, por SFTP, só leitura) copia o arquivo; sanitiza-se (serial, descrição, nome de host, IP, horário, qualquer texto livre) para fixture em `agents/edge/internal/olt/testdata/`; parser + teste de ouro; só então `Validated=true` no catálogo (Edge e nuvem, mesmo hash de versão do catálogo) e o PR passa pelo Codex.
- **Janela:** um lote por janela combinada (as janelas de coleta são de 15 min); o responsável pode interromper a qualquer momento retirando a lista `olt_capture` e reiniciando o Edge. Nada de escrita é possível por este caminho (a lista só aceita IDs do catálogo, renderizados pelo mesmo `Render`).

### 4. O banco (nuvem da plataforma, RLS forçada; nada fica "só" no Edge além da fila de entrega)
- `olt_query_latest(tenant_id, olt_id, query_id, params_key, data jsonb, observed_at, received_at, source, version)` — chave única `(tenant_id, olt_id, query_id, params_key)`; upsert só se `observed_at` for mais novo.
- `olt_metric_samples(tenant_id, olt_id, metric, scope_key, value numeric, at)` — série, retenção 400 dias.
- Escrita só pela rota do Edge `POST /v1/edge/olt-query-results` (service account `edge_agent`, mesma verificação de dono/época da OLT; o formato do `data` conferido pela MESMA função que confere o resultado do job, `olt_query.check_result`, ampliada a cada consulta nova).
- Leitura: `GET /v1/olts/{id}/queries/{q}/latest` (inventory:read + olt_query:run) com `observed_at` e idade; a tela mostra "dado de HH:MM (há N min)". Um valor mais velho que o TTL é marcado como defasado, nunca apresentado como atual.

### 5. Orçamento da sessão (a coleta tem prioridade absoluta)
Ordem dentro da sessão: coleta → consultas sob demanda (≤5) → rotinas vencidas (≤6 comandos) → captura (≤3). Tudo dentro do que resta do prazo da coleta e do arrendamento (regra de 30 s de ADR-0029). Falha de qualquer etapa aborta as seguintes; a próxima janela tenta de novo. Rotinas não competem entre si: no máximo as 2 mais atrasadas por sessão.

## Consequências
- Menos sessão de OLT por informação: um pedido repetido dentro do TTL não toca o equipamento; a leitura de alarmes/temperatura deixa de depender de alguém pedir.
- O banco cresce: séries limitadas por retenção e por cadência (≤ ~10 amostras/h/OLT); tamanho estimado a medir depois do lote 1.
- Mais código: tabelas, rota de ingestão, rotinas no Edge, cache na API e na tela. Entregue em PRs separados (ordem em NEXT_ACTIONS), cada um com Codex.
- Risco aceito: o formato das saídas não executadas é desconhecido; por isso a captura vem ANTES de qualquer parser e cada lote termina com fixture sanitizada.

## Ordem de entrega
1. Modo captura no Edge (+ este ADR) → reimplantar → **lote 1** na janela.
2. Parsers do lote 1 + validação no catálogo (Edge e nuvem) + testes de ouro.
3. Tabelas, ingestão, cache primeiro na API/tela.
4. Rotinas no Edge (config, orçamento, cadências) com o lote 1.
5. Lotes 2 a 5, um por vez, repetindo 1–2 (e 4 se houver rotina).

## Alternativas descartadas
Consultar tudo a cada coleta (pesado: ~1 comando/s); sondar por SNMP (agente frágil e compartilhado); capturar por login separado (enfraquece o guard); guardar a saída crua na nuvem (dado de cliente); cache só no Edge (a UI e a API não enxergam, e o histórico se perde com o host).
