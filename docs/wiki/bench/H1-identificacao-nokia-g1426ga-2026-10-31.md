# H1 — identificação (SOMENTE LEITURA) — Nokia G-1426G-A — 2026-10-31

Escopo: leitura. **Nenhuma manobra, nenhuma escrita, nenhum registro de alvo de bancada.** Sem credencial, IP ou dado de cliente.

| Item | Observado |
|---|---|
| CPE no ACS | dispositivo Nokia G-1426G-A (OUI `286FB9`, serial terminado em `…C7DE`); 1 único dispositivo Nokia no ACS; Inform e boot recentes |
| CPE na nuvem | ingerido (fabricante `ALCL`, modelo G-1426G-A); firmware ainda não lido; **sem vínculo ONU↔CPE** |
| ONU na OLT | GPON SN terminado em `…C7DE` (prefixo ASCII `ALCL`), PON `0/0/14`, online, RX −13,28 dBm |
| Vínculo CPE↔ONU | **Igualdade de serial depois de decodificar o prefixo ASCII** (os 8 últimos caracteres e o prefixo `ALCL` coincidem), único entre as 2 ONUs Nokia da PON. O vinculador automático hoje compara o texto cru e não decodifica o prefixo, por isso ainda não criou o vínculo |
| Contexto da PON | `0/0/14` tem 12 ONUs, **2 delas Nokia**, mais ONUs de clientes: a PON NÃO é exclusiva da bancada |

## Pendente antes de qualquer alvo de bancada
Aceite do responsável para esta identidade (serial terminado em `…C7DE`), emenda do ADR-0030 (lista fechada com mais de um modelo), `bench-target-add`, entrada na lista local do Edge e registro de capacidades por fabricante/modelo/firmware. Ajuste opcional do vinculador para decodificar o prefixo ASCII do GPON SN (com teste).
