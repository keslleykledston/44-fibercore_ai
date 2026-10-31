# Speed — 1ª execução real de download na ONT de bancada — 2026-10-31 — CONCLUÍDA (resultado PARCIAL por duração curta)

Escopo: SOMENTE a ONT de bancada (Huawei EG8145V5 `V5R019C10S350`, serial de bancada `…7AA5`). Sem credencial, endereço ou dado de cliente. Destino lógico `core-lab` (nó de teste do próprio LAB), perfil `10mb`.

## Resumo
O download TR-143 foi executado pela ONT de bancada contra o nó de teste e o Edge leu os contadores do aparelho. O que destravou a execução foi o Connection Request: o ACS passou a usar a credencial por dispositivo (remoção da chave global `cwmp.connectionRequestAuth`; ver `H-connection-request-diagnostico-eg8145v5-2026-10-31.md`). Resultado: 10.270.776 bytes de teste em 352 ms, 233,43 Mbps. **Classificado como PARCIAL (`too_short`)**: 352 ms está abaixo dos 3 s mínimos. O número NÃO representa a capacidade da linha; serve para provar que a operação funciona de ponta a ponta. Uma medição confiável exige o perfil de 200 MB (a esta taxa, ~7 s).

## Campos exigidos (ADR-0030 item 7)
- **Hash da intenção:** 3dd8197bb5616b25b8f9934e0bba5478ac619d52fd325c95bac53bbca08fb4aa (job `fe280f42-ce78-462c-b8fe-dfc5bd17d181`; execução `f62e3b53-b4ae-495c-a71b-e2d266120492`)
- **Identidades observadas:** ACS com exatamente 1 dispositivo de OUI `00259E`, classe `EG8145V5` e o serial de bancada da lista local (`…7AA5`); CPE da bancada `f851bae3…` vinculado à ONU 0/0/14, ONT-ID 10; nenhuma tarefa pendente e nenhuma falha no ACS antes de começar; último Inform há 154 s.
- **Estado antes:** `DownloadDiagnostics.DiagnosticsState` = `Completed` de uma execução anterior (sonda de 3xx de 2026-10-31); nenhuma tarefa pendente; flag `speed_diagnostics` desligada; alvo de bancada destravado; autorização de uso único `07f2ec17…` (primeira execução, par exato `core-lab` + `10mb`).
- **Estado depois:** `DiagnosticsState` = `Completed`; `TestBytesReceived` = 10270776; `TotalBytesReceived` = 10581737; `TotalBytesSent` = 571; duração `EOMTime − BOMTime` = 352 ms. O relógio da ONT está defasado (reporta horário local marcado como UTC), por isso só a diferença entre `BOMTime` e `EOMTime` é usada. Job `SUCCEEDED` com `speed_done` e pós-checagem OK; flag `speed_diagnostics` desligada ao fim.
- **Resultado da restauração:** o diagnóstico não altera configuração persistente da ONT; o estado `DiagnosticsState` voltou a `Completed` e nenhuma tarefa ficou na fila do ACS (0 pendentes). Alvo de bancada não ficou travado.
- **Versões:** Edge `0.1.0-lab-853e99e` (seção `speed`); firmware da ONT `V5R019C10S350`; nuvem no alembic 0037; GenieACS 1.2.16.
- **Aprovador:** conta de serviço `lab-speed-req` (pedido) e `lab-speed-appr` (aprovação), ambas `isp_admin`, diferentes entre si; autorização de uso único registrada pelo owner CLI em nome do responsável (chat da sessão: "vamos seguir com a Nokia e Huawei", precedido de "em seguida vamos pra o teste de bancada real").
- **Horário:** 2026-10-31 22:10:05 UTC a 22:10:25 UTC (job: APPROVED 22:10:15, SUCCEEDED 22:10:25).
- **Aceite do responsável:** REGISTRADO. O responsável aceitou esta evidência no chat da sessão em 2026-10-31 ("aceito download") para promover `speed_test_download` a `observed` neste modelo e firmware. Uma promoção feita antes do aceite tinha sido revertida; esta é a promoção com o aceite.

## Observações
- A origem pública que chegou ao nó foi um único endereço, o mesmo da lista permitida (conferido por captura de SYNs no host do nó; endereço não registrado aqui).
- O aceite do risco de 3xx continua vigente (até 2026-11-30); o nó nunca redireciona.
- Não verificado: confiabilidade do número (precisa de 200 MB), upload, repetições (3) e comparação com medição cabeada.

## Verificação do registro após a reversão (consulta ao banco do LAB, 2026-10-31 22:13 UTC)
Saída do owner CLI: `capability speed_test_download/tr069 on Huawei Technologies Co., Ltd EG8145V5 V5R019C10S350: supported/identified`.
Linha em `device_capabilities` (campos sanitizados): `speed_test_download | supported | identified | verificado em 2026-10-31 22:10:25+00`.
A promoção a `observed` só será refeita depois do aceite escrito do responsável, com o mesmo comando e esta evidência.
