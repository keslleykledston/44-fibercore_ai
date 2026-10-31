# H1 — identificação (SOMENTE LEITURA) — Nokia G-1426G-A — 2026-10-31

Escopo: leitura. **Nenhuma manobra, nenhuma escrita, nenhum registro de alvo de bancada.** Sem credencial, IP ou dado de cliente.

| Item | Observado |
|---|---|
| CPE no ACS | dispositivo Nokia G-1426G-A (OUI `286FB9`, serial terminado em `…C7DE`); 1 único dispositivo Nokia no ACS; Inform e boot recentes |
| CPE na nuvem | ingerido (fabricante `ALCL`, modelo G-1426G-A); firmware ainda não lido; **sem vínculo ONU↔CPE** |
| ONU na OLT | GPON SN terminado em `…C7DE` (prefixo ASCII `ALCL`), PON `0/0/14`, online, RX −13,28 dBm |
| Vínculo CPE↔ONU | **Igualdade de serial depois de decodificar o prefixo ASCII** (os 8 últimos caracteres e o prefixo `ALCL` coincidem), único entre as 2 ONUs Nokia da PON. O vinculador automático hoje compara o texto cru e não decodifica o prefixo, por isso ainda não criou o vínculo |
| Contexto da PON | `0/0/14` tem 12 ONUs na coleta de 2026-10-31 16:59 UTC (2 com prefixo Nokia). Só as ONUs de bancada conhecidas estão na lista de bancada; a natureza das demais (cliente ou outra) **não foi verificada**, então a PON deve ser tratada como NÃO exclusiva da bancada, com possível tráfego de produção |

## Pendente antes de qualquer alvo de bancada
Aceite do responsável para esta identidade (serial terminado em `…C7DE`), emenda do ADR-0030 (lista fechada com mais de um modelo), `bench-target-add`, entrada na lista local do Edge e registro de capacidades por fabricante/modelo/firmware. Ajuste opcional do vinculador para decodificar o prefixo ASCII do GPON SN (com teste).

## Fonte dos números da PON
Consulta somente leitura ao banco da nuvem do LAB (escopo do provedor da bancada), repetida em 2026-10-31 depois da coleta de OLT das 16:59 UTC:
```sql
SELECT count(*), min(o.observed_at), max(o.observed_at),
       count(*) FILTER (WHERE o.serial LIKE '5A544547%') AS prefixo_zteg,
       count(*) FILTER (WHERE o.serial LIKE '414C434C%') AS prefixo_alcl
FROM onus o JOIN pon_ports p ON p.id = o.pon_id AND p.tenant_id = o.tenant_id
WHERE p.pon_path = '0/0/14'
  AND o.observed_at >= (SELECT max(observed_at) FROM onus) - interval '30 minutes';
```
Resultado: **12** linhas, todas com `observed_at` = 2026-10-31 16:59:01 UTC (`min` = `max`, ou seja, uma única coleta, sem linhas antigas), das quais 5 com prefixo `ZTEG` e 2 com `ALCL`. A família vem dos 4 primeiros bytes do GPON SN em hex lidos como ASCII. Não há exportação versionada (seriam seriais de ONUs).
