# Speed — download na ZTE F670L de bancada — 2026-11-01

Escopo: SOMENTE a ONT de bancada ZTE F670L (firmware `V9.0.11P1N10B`), pela sua única WAN (PPPoE, a de serviço, que também carrega a gerência). Destino lógico `core-lab`. Sem credencial, endereço ou dado de cliente.

- **Hash da intenção:** 200 MB: `64588b033fc9bbddba7732f369a16c96c094d4491ba92c0b0f640d463f5cfa2f` (job `e2b997e3-bb75-4e3c-8f24-4530106df730`, execução `8e041492-2604-4083-bf24-7833bfd214a3`); 10 MB: `ce38efe06f0d6993aecc4ee838b69491c3805bb48b2d82e4c69cbfd4aa87361e` (job `2728f4dc-b783-4c7e-8ab9-ea5d6d87d9b2`, execução `6006a148-4733-4a32-af43-fb50002fc782`). Operação `speed_test_download`, parâmetros: destino `core-lab` e o perfil.
- **Identidades observadas:** CPE no ACS, exatamente 1 documento: OUI `FC4009`, classe `F670L`, serial `ZTE3BJNP5359122`, device_id `FC4009-F670L-ZTE3BJNP5359122`, igual ao alvo de bancada da nuvem (`992da7cd-4fc0-4ebd-ad04-ffe444d9c5b0`) e à lista local do Edge. ONU na OLT, associada por decisão humana: serial GPON `5A544547D1EDA1A3`, PON 0/0/14, ONT-ID 11 (identidade física NÃO provada por evidência independente; ver o H2 da ZTE). WAN de serviço usada em `Interface`: `InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1.WANPPPConnection.2` (única WAN, `Connected`, aceita pelo responsável).
- **Estado antes:** último Inform há 48 s (10 MB) e 13 s (200 MB); nenhuma tarefa pendente no ACS; flag `speed_diagnostics` desligada; alvo destravado.
- **Estado depois:** nenhuma tarefa pendente; flag `speed_diagnostics` desligada ao fim de cada execução; `DownloadDiagnostics` em `Completed`; o `DownloadURL` aponta ao perfil da última execução.
- **Resultado da restauração:** o teste não altera configuração do aparelho além das folhas de `DownloadDiagnostics` do próprio teste; não há valor a restaurar.
- **Versões:** Edge `0.1.0-lab-abb2284` nas duas execuções aprovadas (`0.1.0-lab-777ec89` nas tentativas 1 e 2, abaixo); firmware do CPE `V9.0.11P1N10B`; OLT Huawei MA5608T; nó de teste `tools/speed-node` do LAB, 4 origens permitidas.
- **Aprovador:** conta de serviço de ensaio diferente da que pediu o teste (quem pede ≠ quem aprova ≠ quem autorizou). Autorização de uso único do responsável com `--first-run` e o par exato `core-lab` + perfil, aberta no chat da sessão.
- **Horário:** 10 MB: job criado 2026-11-01 04:45:18 UTC, concluído 04:45:37; 200 MB: job criado 04:50:17, concluído 04:50:42 (UTC).
- **Aceite do responsável:** dado em 2026-11-01 pelo chat da sessão ("1. aceite", em resposta à pergunta "Você aceita o resultado do download da ZTE?", feita com este documento já escrito e revisado, incluindo as seções de limites e de tentativas falhas), sobre o resultado do download de 200 MB (`completed`, 257,86 Mbps). O 10 MB (`partial`) não é evidência de capacidade.

## Resultados (gravados pela plataforma)
| Perfil | Desfecho | Vazão | Duração | Bytes |
|---|---|---|---|---|
| 10 MB | `partial` / `too_short` | 226,63 Mbps | 353 ms | 10 000 000 |
| 200 MB | `completed` | **257,86 Mbps** | 6 205 ms | 200 000 000 |

O 200 MB passa do mínimo de 3 s e é o único resultado confiável. É o caminho ONT → nó de teste do LAB pela WAN PPPoE da ZTE: um único sentido, uma repetição, sem referência cabeada. Não é a velocidade contratada nem a capacidade da PON.

## Tentativas anteriores (nenhuma deu medição)
1. **Job `5cda3c4f-…`** (Edge `777ec89`): `device_error`, `DiagnosticsState = Error_InitConnectionFailed`. Observado: nesse momento o `ufw` do host só tinha regras para a porta do nó vindas do host do Edge e da origem da Huawei, nenhuma para a origem pública da ZTE (a lista foi lida DEPOIS do disparo, não durante). Explicação provável (hipótese, sem captura de SYN naquele disparo): o firewall descartou a conexão da ZTE. O que a sustenta: depois de abrir a regra para essa origem, o disparo seguinte conectou e baixou os 10 000 000 bytes. Não afirmo que nenhum byte trafegou nessa tentativa.
2. **Job `58a4ec1b-…`** (Edge `777ec89`): `no_timestamps`. Observado: no ACS, `DiagnosticsState = Completed`, `TestBytesReceived = 10000000`, `BOMTime` e `EOMTime` com data de 1970 (relógio da ZTE sem sincronismo); o código do Edge dessa versão descartava horários com ano anterior a 2000 (leitura do código); a nuvem recebeu relatório sem horários. Explicação provável (hipótese): o descarte dos horários de 1970 produziu o `no_timestamps`. O que a sustenta: depois do ajuste do Edge (só a diferença BOM→EOM é usada), a mesma ZTE passou a dar vazão numérica; não guardei o relatório bruto enviado pelo Edge naquele job.
3. **Job `d392d425-…`** (200 MB, Edge `abb2284`): recusado por `pacing` (44 s depois do teste anterior), 8 ms depois de aceito, sem nenhuma escrita ao aparelho. O alvo ficou travado e foi destravado com `bench-unlock` depois de conferir no log do Edge e no ACS que nada chegou ao aparelho.

## Leitura e limites
- A ZTE não preenche os totais do teste no cálculo; a vazão vem de `TestBytesReceived` e da diferença BOM→EOM no relógio do aparelho (sem sincronismo, só a diferença vale).
- A ZTE SEGUE 3xx; o teste só é elegível com o aceite vigente (`7f71b13a-…`, até 2026-11-30, `core-lab`).
- O nó não tem controle de taxa nem de volume; a origem pública da ZTE foi incluída na lista sem confirmar quem mais a usa (ver o aceite).
- A identidade física entre este CPE e a ONT 11 da OLT segue sem prova independente.

## O que ainda falta (homologação do download)
- Repetições do 200 MB (ao menos 3) para ver a variação; comparação com medição cabeada de referência (precisa de alguém na bancada); upload (próximo passo; verificar antes, só leitura, `UploadDiagnostics` já existe no aparelho).

## Alcance do aceite
`speed_test_download` passa a `observed` para ZTE F670L `V9.0.11P1N10B` por TR-069, no nível de modelo e firmware do CPE do ACS, pela WAN PPPoE dela até o nó `core-lab`, com o aceite de risco de 3xx vigente. Não promove a identidade física do alvo, não vale como velocidade contratada nem como capacidade da PON, e não cobre o upload.
