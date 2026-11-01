# Ping — primeiros pings reais nas ONTs de bancada (ZTE F670L e Huawei EG8145V5) — 2026-11-01

Escopo: SOMENTE as duas ONTs de bancada, pela WAN PPPoE de serviço de cada uma. Destino lógico `core-lab` (o nó de teste do LAB; o endereço existe só na configuração local do Edge). Sem credencial, endereço ou dado de cliente. O ping é o `IPPingDiagnostics` do aparelho: 5 repetições, timeout de 1000 ms, fixados pelo Edge.

- **Hash da intenção:** os parâmetros assinados do job são só o id lógico `core-lab` (hash exato registrado nas autorizações de uso único). ZTE: autorização `39a4419e-742c-4084-839d-138e730fc9da`, job `32acccc1-9b62-4a8b-bd48-881609baeeec`, execução `85d0b0ad-1c66-4039-8c36-2a980dd0a50d`. Huawei: autorização `42d80ae6-b843-41e5-a41d-fc3f907eb85f` (job `688b0f09-240a-49bd-a07e-46911bb0b7e0`) e uma repetição (job `26ff44d7-e379-42b1-9367-34e1840ae7a3`).
- **Identidades observadas:** CPE no ACS com exatamente 1 documento por aparelho, igual ao alvo de bancada da nuvem e à lista local do Edge: ZTE `FC4009-F670L-ZTE3BJNP5359122` (alvo `992da7cd-4fc0-4ebd-ad04-ffe444d9c5b0`) e Huawei `00259E-EG8145V5-48575443E2247AA5` (alvo `f851bae3-0f58-4c8b-aa86-2849d14e8263`).
- **Estado antes:** último Inform há 169 s (ZTE) e 54 s (Huawei); nenhuma tarefa pendente no ACS; flag `quality_active_tests` desligada; alvos sem trava de escrita (a ZTE foi destravada com motivo registrado depois da tentativa 1, abaixo).
- **Estado depois:** nenhuma tarefa pendente; flag `quality_active_tests` desligada ao fim de cada execução; alvos sem trava de escrita; `IPPingDiagnostics` no estado final do último teste.
- **Resultado da restauração:** não há configuração a restaurar: o teste só escreve as folhas de `IPPingDiagnostics` do próprio teste (`Interface`, `Host`, `NumberOfRepetitions`, `Timeout`, `DiagnosticsState`) e nenhuma WAN, Wi-Fi ou credencial foi escrita.
- **Versões:** Edge `0.1.0-lab-74719f0` na tentativa 1 e `0.1.0-lab-90d6b9d` nas demais; firmware ZTE `V9.0.11P1N10B`, Huawei `V5R019C10S350`; nuvem com a migração 0038.
- **Aprovador:** conta de serviço de ensaio diferente da que pediu o teste (quem pede ≠ quem aprova ≠ quem autorizou). Autorizações de uso único com `--first-run`, abertas a partir da ordem do responsável no chat ("Ping real: pode executar agora", 2026-11-01).
- **Horário:** tentativa 1 (ZTE) 10:19:52 UTC; ZTE concluído 10:37:19; Huawei 10:38:23 e repetição 10:40:30 (UTC). Intervalo mínimo de 1 min do Edge respeitado.
- **Aceite do responsável:** PENDENTE. Sem aceite escrito, `ping_test` segue `identified` nos dois modelos.

## Resultados (gravados pela plataforma)
| Aparelho | Execução | Enviados | Respostas | Perda | Mín / média / máx |
|---|---|---|---|---|---|
| ZTE F670L | 1 (Edge `74719f0`) | — | — | — | `error` / `timeout` (ver abaixo) |
| ZTE F670L | 2 | 5 | 5 | 0 % | 11 / 12 / 12 ms |
| Huawei EG8145V5 | 1 | 5 | 1 | 80 % | 11 / 11 / 11 ms |
| Huawei EG8145V5 | 2 (repetição) | 5 | 1 | 80 % | 11 / 11 / 11 ms |

## O que o teste real mostrou (e os testes com Edge de mentira não)
- **O IPPing termina em `Complete`, não em `Completed`.** Na tentativa 1 a ZTE mediu (5 de 5) mas informou `DiagnosticsState = Complete`; o Edge esperava `Completed` e o job falhou por `timeout`. Corrigido no Edge (`Complete` é terminal e sai no relatório como `Completed`), com revisão do Codex (`raw/388-*`, `raw/389-*`, approve na rodada 2). O alvo ficou travado pela falha e foi destravado com motivo (aparelho concluiu; sem tarefa pendente nem falha no ACS).
- **A Huawei devolve 1 de 5, nas duas execuções, e a ZTE devolve 5 de 5 para o mesmo destino.** Isto NÃO está explicado: pode ser o comportamento do `IPPingDiagnostics` da Huawei, o caminho dessa WAN ou limitação de ICMP no destino. Não afirmo perda de rede. Antes de aceitar o ping da Huawei como medida de qualidade é preciso entender a causa (por exemplo, comparar com um ping de outra origem pela mesma WAN, que não está fora do alcance deste projeto mas precisa de alguém na bancada).
- Sem jitter (só mínimo, média e máximo) e sem DNS (nenhum dos dois expõe `NSLookupDiagnostics`), como já medido.

## O que ainda falta
- Repetições (ao menos 3, em dias diferentes para qualquer promoção além da bancada) e a causa dos 80 % da Huawei.
- Aceite escrito do responsável, por modelo, sobre o que quiser aceitar.

## Alcance
Quando houver aceite, `ping_test` entra como `observed` só para o modelo/firmware aceito, como evidência de UMA execução confiável. A Huawei, no estado atual, não deveria ser aceita sem a causa dos 80 %. Não é homologação abrangente.
