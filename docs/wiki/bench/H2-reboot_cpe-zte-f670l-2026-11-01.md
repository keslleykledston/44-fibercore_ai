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

## Observação da OLT (coleta regular, sem captura nova)
Fonte: inventário da plataforma (coleta de 15 em 15 minutos pelo Edge, somente leitura). Nenhum comando novo foi enviado à OLT.
- **Coleta de 03:26:01 UTC:** a ONU declarada como par da ZTE pelo vínculo confirmado por uma pessoa (PON 0/0/14) apareceu `offline` (transição `online→offline`). O reinício foi despachado às 03:26:26 UTC.
- **Coleta de 03:46:01 UTC:** a mesma ONU voltou `online` (RX -14,73 dBm; antes -14,66 dBm).
- **Especificidade:** desde as 03:00 UTC houve 3 transições de estado em toda a OLT. Duas são desta ONU (as de cima). A terceira é de OUTRA ONU, de outra PON, às 03:46:01 UTC, sem relação com a manobra. Na PON 0/0/14 só esta ONU mudou de estado na janela.
- **Limites:** `observed_at` marca o INÍCIO da coleta, que leva alguns minutos, então a ordem exata entre a leitura da ONU e o despacho às 03:26:26 não está estabelecida (a coleta começou 25 s antes do despacho). Os relógios da OLT, do Edge e do ACS não foram correlacionados. O "último down" da OLT (`olt_down_at`) não veio preenchido; nenhum horário de queda lido na OLT foi comparado com o `_lastBoot` do ACS.
- **Leitura honesta:** é um indício coerente com o vínculo (a ONU da PON 0/0/14 que caiu e voltou na janela do reinício da ZTE), não uma prova. Não distingue a ZTE de outra ONU da mesma PON que tivesse caído nessa janela sem outra mudança de estado registrada; também não exclui coincidência.

## O que NÃO foi observado
- **Identidade física do alvo:** o reinício comprova que a manobra atingiu o CPE do ACS (`_lastBoot` novo). Que esse CPE seja a ONT 11 da OLT continua NÃO provado; o indício da coleta regular acima é coerente, mas não conclusivo. Uma captura supervisionada com horários de queda lidos na OLT só se justifica se o responsável quiser mais prova.

## Uso desta execução
Esta execução NÃO é evidência de homologação do `reboot_cpe` na ZTE e não promove a capacidade. Ela só registra que o caminho com portões entregou o reinício ao CPE do ACS.

## Aceite
Pendente. A capacidade `reboot_cpe` da ZTE segue `identified`: a promoção para `observed` exige aceite escrito do responsável sobre este resultado.
