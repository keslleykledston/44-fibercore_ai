# Evidência de manobra de bancada — H2 `reboot_cpe` na ZTE F670L — 2026-11-01

Escopo: SOMENTE a ONT de bancada ZTE F670L (firmware `V9.0.11P1N10B`). Sem credencial, IP, nome de cliente ou saída crua.

- **Hash da intenção:** `ed602fbed41c51779421219d87d7797c5c4fdd4186d8fcdeab1a1c52e8eaaace` (job `a2a22f05-847d-4199-89e1-237db6c41ae6`, operação `reboot_cpe`, sem parâmetros)
- **Pré-requisitos formais (ADR-0030 item 2) e seu limite:** o vínculo ONU↔CPE foi marcado `confirmed` por uma pessoa em 2026-11-01 03:23:52 UTC, ANTES do `bench-target-add` (`owner_epoch 2`). Essa confirmação é uma DECISÃO HUMANA sobre o H1 da ZTE, cuja evidência é sugestiva e não conclusiva; ela NÃO prova a correspondência física entre o CPE do ACS e a ONT 11 da OLT. Também existem: autorização de escrita do responsável no chat da sessão, identidade na lista local do Edge e capacidade `reboot_cpe` registrada como `supported`/`identified` para este modelo e firmware.
- **Autorização prévia:** `c6630dfb-5ed3-471a-a558-1d3419109551`, uso único, janela de 30 min, com `--first-run` (substitui a entrada `observed` que ainda não existe no registro).
- **Identidades observadas:** no ACS, exatamente 1 documento com o id `FC4009-F670L-ZTE3BJNP5359122` (fabricante ZTE, modelo F670L, firmware `V9.0.11P1N10B`), igual à identidade do alvo de bancada da nuvem e da lista local do Edge. A releitura de identidade do Edge antes do envio faz parte do caminho com portões que terminou em `SUCCEEDED`; não conferi o log do Edge nesta sessão.
- **Estado antes:** `_lastBoot` no ACS = 2026-10-31T22:22:41Z; último Inform há 126 s; nenhuma tarefa pendente na ONT.
- **Estado depois:** `_lastBoot` no ACS = 2026-11-01T03:27:50Z (posterior ao envio, lido por fora no ACS); nenhuma tarefa pendente.
- **Resultado:** job `SUCCEEDED`; detalhe da pós-checagem do Edge: "reboot delivered and the device came back", `postcheck_ok: true`.
- **Horário:** (UTC) job criado 03:26:16; despacho 03:26:26 (hora local da sessão 23:26); `_lastBoot` novo 03:27:50; job `SUCCEEDED` 03:27:57.
- **Aprovador:** conta de serviço de ensaio, pelo caminho "aprovação da bancada" do ADR-0030, como no H2 da Huawei.
- **Versões:** firmware do CPE `V9.0.11P1N10B`; OLT Huawei MA5608T.
- **Resultado da restauração:** não há estado a restaurar num reinício; o retorno foi OBSERVADO pelo novo boot informado ao ACS.

## Observação da OLT (coleta regular, sem captura nova)
Fonte: inventário da plataforma (coletas observadas às 03:06:01, 03:26:01 e 03:46:01 UTC, ou seja, a cada 20 minutos neste período, pelo Edge, somente leitura). Nenhum comando novo foi enviado à OLT. Os horários abaixo são os INÍCIOS das coletas (`observed_at`); cada coleta leva alguns minutos e as leituras não localizam no tempo a diferença de estado observada.
- **Coleta iniciada às 03:06:01 UTC:** a mesma ONU constava `online` (RX -14,66 dBm).
- **Coleta iniciada às 03:26:01 UTC:** a ONU que o vínculo confirmado por uma pessoa associa à ZTE (PON 0/0/14) constava `offline`.
- **Coleta iniciada às 03:46:01 UTC:** a mesma ONU constava `online` (RX -14,73 dBm; antes -14,66 dBm).
- **Contagem (pelos estados registrados):** desde as 03:00 UTC foram registradas 3 diferenças de estado entre coletas na OLT inteira: duas desta ONU (entre as coletas de 03:06 e 03:26 e entre as de 03:26 e 03:46) e uma de OUTRA ONU, de outra PON, entre as coletas de 03:26 e 03:46. A contagem não é o total de mudanças ocorridas: não detecta mudanças intermediárias não amostradas (inclusive queda e retorno entre duas coletas) nem determina o instante de nenhuma.
- **O que isto diz:** entre as coletas de 03:06 e 03:26 o estado observado difere (`online` → `offline`), e entre as de 03:26 e 03:46, (`offline` → `online`). Nada mais.
- **O que isto NÃO diz:** não atribui a diferença de estado ao reinício. O despacho foi às 03:26:26 UTC, 25 s DEPOIS do início da coleta que registrou `offline`; a leitura pode ter ocorrido antes ou depois do despacho (intervalo indeterminado), e os relógios da OLT, do Edge e do ACS não foram correlacionados. O "último down" da OLT (`olt_down_at`) não veio preenchido. A coleta também não é evidência independente de qual equipamento do ACS corresponde à ONT 11: ela só observa a ONU previamente associada por decisão humana.

## O que NÃO foi observado
- **Identidade física do alvo:** o reinício comprova que a manobra atingiu o CPE do ACS (`_lastBoot` novo). Que esse CPE seja a ONT 11 da OLT continua NÃO provado; a coleta regular acima não o corrobora de forma independente. Uma captura supervisionada com horários de queda lidos na OLT só se justifica se o responsável quiser mais prova.

## Uso desta execução e aceite
- **Aceite do responsável:** dado em 2026-11-01 pelo chat da sessão ("aceito o H2"), depois de o responsável ler que: o resultado prova que o caminho com portões entregou o reinício ao CPE do ACS (`_lastBoot` novo); a identidade física entre esse CPE e a ONT 11 da OLT NÃO está provada; a coleta da OLT não corrobora essa identidade de forma independente.
- **Alcance da promoção:** `reboot_cpe` passa a `observed` para ZTE F670L `V9.0.11P1N10B` por TR-069, no nível de modelo e firmware do CPE do ACS. Não promove nem confirma a identidade física do alvo.
