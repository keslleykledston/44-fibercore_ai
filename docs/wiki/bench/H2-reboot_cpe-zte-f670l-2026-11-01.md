# Evidência de manobra de bancada — H2 `reboot_cpe` na ZTE F670L — 2026-11-01

Escopo: SOMENTE a ONT de bancada ZTE F670L (firmware `V9.0.11P1N10B`). Sem credencial, IP, nome de cliente ou saída crua.

- **Hash da intenção:** `ed602fbed41c51779421219d87d7797c5c4fdd4186d8fcdeab1a1c52e8eaaace` (job `a2a22f05-847d-4199-89e1-237db6c41ae6`, operação `reboot_cpe`, sem parâmetros)
- **Pré-requisitos formais (ADR-0030 item 2) e seu limite:** o vínculo ONU↔CPE foi marcado `confirmed` por uma pessoa em 2026-11-01 03:23:52 UTC, ANTES do `bench-target-add` (`owner_epoch 2`). Essa confirmação é uma DECISÃO HUMANA sobre o H1 da ZTE, cuja evidência é sugestiva e não conclusiva; ela NÃO prova a correspondência física entre o CPE do ACS e a ONT 11 da OLT. Também existem: autorização de escrita do responsável no chat da sessão, identidade na lista local do Edge e capacidade `reboot_cpe` registrada como `supported`/`identified` para este modelo e firmware.
- **Autorização prévia:** `c6630dfb-5ed3-471a-a558-1d3419109551`, uso único, janela de 30 min, com `--first-run` (substitui a entrada `observed` que ainda não existe no registro).
- **Estado antes:** `_lastBoot` no ACS = 2026-10-31T22:22:41Z; último Inform há 126 s; nenhuma tarefa pendente na ONT.
- **Estado depois:** `_lastBoot` no ACS = 2026-11-01T03:27:50Z (posterior ao envio, lido por fora no ACS); nenhuma tarefa pendente.
- **Resultado:** job `SUCCEEDED`; detalhe da pós-checagem do Edge: "reboot delivered and the device came back", `postcheck_ok: true`.
- **Horário (UTC):** job criado 03:26:16; despacho 03:26:26 (hora local da sessão 23:26); `_lastBoot` novo 03:27:50; job `SUCCEEDED` 03:27:57.
- **Aprovador:** conta de serviço de ensaio, pelo caminho "aprovação da bancada" do ADR-0030, como no H2 da Huawei.
- **Versões:** firmware do CPE `V9.0.11P1N10B`; OLT Huawei MA5608T.
- **Restauração:** não há estado a restaurar num reinício; o retorno foi OBSERVADO pelo novo boot informado ao ACS.

## O que NÃO foi observado
- **Lado da OLT:** a última coleta da OLT anterior à manobra é de 03:06 UTC (`online`, RX -14,66 dBm). Nenhuma transição `offline` da ONU foi registrada pela coleta regular, e o reinício durou cerca de 2 minutos. Este documento não afirma que a OLT viu a queda e a volta.
- **Identidade física do alvo:** o reinício comprova que a manobra atingiu o CPE do ACS (`_lastBoot` novo). Que esse CPE seja a ONT 11 da OLT continua NÃO provado: depende de uma captura supervisionada da OLT depois da manobra.

## Uso desta execução
Esta execução NÃO é evidência de homologação do `reboot_cpe` na ZTE e não promove a capacidade. Ela só registra que o caminho com portões entregou o reinício ao CPE do ACS.

## Aceite
Pendente. A capacidade `reboot_cpe` da ZTE segue `identified`: a promoção para `observed` exige aceite escrito do responsável sobre este resultado.
