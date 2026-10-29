# ADR-0020: Envelope de proveniência/frescor nas respostas; `observations` adiada

Status: Accepted (envelope na ONU 360 no PR 36; demais telas conforme forem tocadas; `observations` segue adiada) | Data: 2026-10-29 | Owner: equipe | Origem: adendo v2.2, FC22-003

## Contexto
O repo já calcula frescor na leitura (`_fresh`, 15 min) e guarda `observed_at` por entidade; a UI mostra `DataFreshness`. Falta um campo uniforme de **fonte** e **qualidade**, e o estado `conflict` (duas fontes discordam). A tabela `observations` do adendo só faz sentido com telemetria (Wi-Fi/WAN/óptica histórica), que **não coletamos** (NBI lido com projeção mínima).

## Decisão
1. Respostas de leitura novas/alteradas carregam, por bloco externo: `source` (`olt_snapshot`, `genieacs_nbi`, `erp_csv`, …), `observed_at`, `quality` (`fresh|stale|unknown`; `conflict` só quando houver 2ª fonte para o mesmo campo). 2. **Silêncio do coletor nunca vira estado do equipamento** (mantém ADR-0018). 3. Tabela `observations` **não é criada agora**; entra junto da primeira telemetria real, com particionamento decidido por volume medido.

## Consequências
Sem migração para o envelope (só serialização). Teste: Edge parado → `stale`/`unknown`, nunca ONU offline em massa (já coberto por `test_noc.py`; ampliar para os novos blocos).

**Implementado (PR 36)**: `provenance{state, olt, pon}` na ONU 360 (`source`, `observed_at`, `quality` calculada na leitura) e componente `SourceChip`. `conflict` continua reservado (sem 2ª fonte).

