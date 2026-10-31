# Speed — download de 200 MB, 3 repetições na ONT de bancada — 2026-10-31 — CONCLUÍDAS (todas `completed`)

Escopo: SOMENTE a ONT de bancada (Huawei EG8145V5 `V5R019C10S350`, serial de bancada `…7AA5`). Destino lógico `core-lab`, perfil `200mb`, uma execução por autorização de uso único. Sem credencial, endereço ou dado de cliente. Registro `speed_test_download` `observed`.

| # | Execução | Desfecho | Mbps | Duração | Bytes de teste |
|---|---|---|---|---|---|
| 1 | `bd06b464-1c9b-47b2-9b77-35ae7513e12b` | `completed` | 331,15 | 4.961 ms | 205.355.216 |
| 2 | `bb757b24-0590-4ef0-be42-a7b4893f3b1c` | `completed` | 330,83 | 4.963 ms | 205.238.236 |
| 3 | `30a61ce3-d18b-4514-b33c-7e05c623487b` | `completed` | 380,93 | 4.309 ms | 205.175.756 |

- Média das 3: 347,64 Mbps; mínimo 330,83; máximo 380,93; amplitude de 14,4 % da média. Todas passam do critério de 3 s, sem motivo de ressalva.
- As duas primeiras ficaram praticamente iguais (≈ 331 Mbps); a terceira foi 15 % maior. **A causa dessa variação não foi investigada** (não há medição cabeada de referência nem monitoramento do host, do nó ou da operadora durante as execuções).
- Estas são medições do caminho **ONT → nó de teste do LAB**, só no sentido de download, em uma única janela de 12 minutos. Não são a velocidade contratada de um cliente nem a capacidade da PON, e 3 amostras não bastam para falar em desempenho típico.
- Para cada execução: job `SUCCEEDED`, flag `speed_diagnostics` desligada ao fim, alvo de bancada sem travamento, 0 tarefas pendentes no ACS ao começar; autorização de uso único com o par exato `core-lab` + `200mb`, aprovada por conta diferente da solicitante. Origem que chegou ao nó (captura de SYNs na primeira): um único endereço, o da lista permitida.
- Autorização do responsável: no chat da sessão, 2026-10-31 ("autorizo", depois de proposta de 2 repetições de 200 MB).

## Falta
- Medição **cabeada de referência** (mesmo nó e janela), com alguém na bancada.
- Upload (ver `H1-speed-upload-eg8145v5-2026-10-31.md`).
- Relatório periódico e repetição em outro horário, para ver a variação ao longo do dia.
