# Speed — upload na ZTE F670L de bancada — 2026-11-01

Escopo: SOMENTE a ONT de bancada ZTE F670L (firmware `V9.0.11P1N10B`), pela sua única WAN (PPPoE, a de serviço, que também carrega a gerência). Destino lógico `core-lab`. Sem credencial, endereço ou dado de cliente.

- **Hash da intenção:** 200 MB: `8226a573e88944a9835cb10064982adb60090dd07ab4e28414055c19bad5ebe6` (job `869ac7d8-aa5f-4d7d-a030-4c56ef7e75c3`, execução `97609d89-a6c9-4b1e-a6bb-ba3407d77460`); 10 MB: `d80f87fbbc4188ab81d52f0e8eddb51a8f424566989db9fce7b6f46727296451` (job `d9515080-b72c-4539-b959-875523ef76b5`, execução `9b4c3aed-22f4-4bd2-a3d5-ad56dc59d22c`). Operação `speed_test_upload`, parâmetros: destino `core-lab` e o perfil.
- **Identidades observadas:** CPE no ACS, exatamente 1 documento: OUI `FC4009`, classe `F670L`, serial `ZTE3BJNP5359122`, device_id `FC4009-F670L-ZTE3BJNP5359122`, igual ao alvo de bancada da nuvem (`992da7cd-4fc0-4ebd-ad04-ffe444d9c5b0`) e à lista local do Edge. ONU na OLT: serial GPON `5A544547D1EDA1A3`, PON 0/0/14, ONT-ID 11. Gate de identidade do ADR-0030 item 2: o vínculo ONU↔CPE está `confirmed` por UMA PESSOA desde 2026-11-01 03:23:52 UTC, antes do `bench-target-add` (ver o H2 da ZTE); essa confirmação é uma decisão humana sobre evidência H1 sugestiva, e a identidade física NÃO está provada por evidência independente. WAN de serviço usada em `Interface`: `InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1.WANPPPConnection.2` (única WAN, `Connected`, aceita pelo responsável).
- **Estado antes:** último Inform há 88 s (10 MB) e 117 s (200 MB); nenhuma tarefa pendente no ACS; flag `speed_diagnostics` desligada; alvo sem trava de escrita (`write_locked` falso).
- **Estado depois:** nenhuma tarefa pendente; flag `speed_diagnostics` desligada ao fim de cada execução; alvo sem trava de escrita; `UploadDiagnostics` no estado final do último teste.
- **Resultado da restauração:** não há configuração a restaurar: o teste só escreve as folhas de `UploadDiagnostics` do próprio teste (`Interface`, `UploadURL`, `TestFileLength`, `DiagnosticsState`) e nenhuma WAN, Wi-Fi ou credencial foi escrita. Observado depois de cada execução: ACS sem tarefa pendente, flag de volta a `off` e alvo sem trava. Não há valor anterior a comparar.
- **Versões:** Edge `0.1.0-lab-2a49480`; firmware do CPE `V9.0.11P1N10B`; OLT Huawei MA5608T; nó de teste `tools/speed-node` do LAB.
- **Aprovador:** conta de serviço de ensaio diferente da que pediu o teste (quem pede ≠ quem aprova ≠ quem autorizou). Autorizações de uso único com `--first-run` e o par exato `core-lab` + perfil: `2191e6ec-844b-4e4e-8bac-27ddd810212c` (10 MB) e `41f00630-79fa-4f7c-8a39-32978a0cef7c` (200 MB), abertas a partir da ordem do responsável no chat ("comece pelo upload e prossiga", 2026-11-01).
- **Horário:** 10 MB: job criado 2026-11-01 05:12:03 UTC, concluído 05:12:23; 200 MB: job criado 05:14:22, concluído 05:14:42 (UTC). Intervalo mínimo de 1 min do Edge respeitado entre os dois.
- **Aceite do responsável:** PENDENTE. Sem aceite escrito a capacidade `speed_test_upload` da ZTE segue `identified`.

## Leitura prévia (H1, só leitura, sem tráfego)
`refreshObject` em `InternetGatewayDevice.UploadDiagnostics` (2026-11-01 ~05:10 UTC): o aparelho lista as folhas de resultado que o Edge exige (`DiagnosticsState`, `BOMTime`, `EOMTime`, `TotalBytesSent`, além de `TestBytesSent` e `TotalBytesReceived`) e declara graváveis `UploadURL`, `TestFileLength`, `Interface` e `DiagnosticsState`. Lista também `NumberOfConnections` (gravável) e as folhas de teste por tempo, que este teste NÃO usa: ele roda uma conexão por arquivo de tamanho fixo. A gravabilidade é a DECLARADA pelo aparelho. O teste real abaixo mostra que o CONJUNTO das escritas funcionou (o aparelho executou o envio e mediu); não li de volta cada folha individualmente depois da escrita, então não afirmo que cada folha declarada gravável foi comprovada.

## Resultados (gravados pela plataforma)
| Perfil | Desfecho | Vazão | Duração | Bytes |
|---|---|---|---|---|
| 10 MB | `partial` / `too_short` | 283,69 Mbps | 282 ms | 10 000 000 |
| 200 MB | `completed` | **346,17 Mbps** | 4 622 ms | 200 000 000 |

O 200 MB passa do mínimo de 3 s e é o único resultado confiável. É o caminho ONT → nó de teste do LAB pela WAN PPPoE da ZTE, no sentido de subida: um único sentido, uma repetição, sem referência cabeada. Não é a velocidade contratada, a capacidade da PON nem a do aparelho.

## Leitura e limites
- **Conflito aparente com o H1 do vínculo, resolvido assim:** o H1 da ZTE concluiu que a evidência é sugestiva e NÃO conclusiva. O ADR-0030 item 2 exige o vínculo `confirmed` por uma pessoa antes do `bench-target-add`, e não uma prova independente: isso foi cumprido em 2026-11-01 03:23:52 UTC. A decisão do responsável de confirmar sobre evidência sugestiva está registrada no H2; a falta de prova independente da identidade física é uma limitação ACEITA e segue registrada, sem ser tratada como resolvida.
- A ZTE SEGUE 3xx; o teste só é elegível com o aceite vigente (`7f71b13a-…`, até 2026-11-30, `core-lab`).
- O nó não tem controle de taxa nem de volume; a origem pública da ZTE foi incluída na lista sem confirmar quem mais a usa (ver o aceite de risco).
- A identidade física entre este CPE e a ONT 11 da OLT segue sem prova independente.
- O relógio do aparelho não é sincronizado; só a diferença BOM→EOM é usada.
- Uma conexão TCP só: em planos altos o resultado pode ficar abaixo do plano (a ZTE expõe `NumberOfConnections`, ainda não usado).

## O que ainda falta (homologação do upload)
- Repetições do 200 MB (ao menos 3, em dias diferentes para qualquer promoção além da bancada) e referência cabeada (precisa de alguém na bancada).
- Aceite escrito do responsável sobre este resultado.

## Alcance
Ao ser aceito, `speed_test_upload` entra como `observed` para ZTE F670L `V9.0.11P1N10B` por TR-069 como evidência de UMA execução confiável (200 MB, 346,17 Mbps, 4,6 s), pelo CPE do ACS e pela WAN PPPoE até o nó `core-lab`. Continuam SEM validação: repetibilidade, referência cabeada, identidade física do alvo, velocidade contratada, capacidade da PON e multiconexão. Não é homologação abrangente.
