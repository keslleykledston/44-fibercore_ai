# H1 — identificação da ONT de bancada (ADR-0030) — 2026-10-30

Somente leitura. Nenhuma escrita foi enviada a equipamento. Sem credencial, IP, nome de cliente ou saída crua.

## Identidade do par (CPE no ACS × ONU na OLT)
- **CPE no ACS:** fabricante Huawei Technologies Co., Ltd, OUI `00259E`, classe `EG8145V5`, serial `48575443E2247AA5` (id GenieACS `00259E-EG8145V5-48575443E2247AA5`); exatamente 1 documento para esse id; sem tarefas pendentes; informa ao ACS com credencial CWMP (autenticação exigida).
- **Firmware do CPE:** `V5R019C10S350` (lido do cache do ACS e já presente no inventário da nuvem desde o PR 59).
- **ONU na OLT:** posição `0/0/14`, estado online, serial GPON terminando em `E2247AA5` (o serial ASCII do CPE `48575443` = "HWTC" + `E2247AA5`); observado pela coleta somente leitura da OLT (SNMP) e por captura CLI supervisionada anterior; vínculo ONU↔CPE `confirmed` na nuvem.
- **Nuvem:** CPE e ONU existem como linhas distintas; a ONT de bancada é a ÚNICA ONT dessa lista; as ONTs de produção do mesmo modelo têm outros seriais.

## Estado de partida (para comparação após a H2)
- WAN: enlace Up, conexão PPP Connected; RX óptico da ONU em torno de -13 dBm (OLT); `_lastBoot` do ACS anterior ao teste.

## Pendências
- **Aceite do responsável:** dado em 2026-10-30, pelo chat da sessão ("está correto"), sobre as identidades acima.
- A igualdade completa do serial GPON da ONU com o do CPE foi observada pelo sufixo e pela vinculação confirmada; o responsável confirma na autorização.
