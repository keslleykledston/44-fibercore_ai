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
Consulta somente leitura ao banco da nuvem do LAB (escopo do provedor da bancada), com o instante da coleta de OLT escolhido **explicitamente** (2026-10-31 16:59:01 UTC):
```sql
SELECT count(*) AS onus,
       count(*) FILTER (WHERE o.serial LIKE '5A544547%') AS prefixo_zteg,
       count(*) FILTER (WHERE o.serial LIKE '414C434C%') AS prefixo_alcl,
       count(DISTINCT o.observed_at) AS instantes, count(DISTINCT o.pon_id) AS pons, count(DISTINCT o.olt_id) AS olts
FROM onus o JOIN pon_ports p ON p.id = o.pon_id AND p.tenant_id = o.tenant_id AND p.olt_id = o.olt_id
WHERE p.pon_path = '0/0/14' AND o.tenant_id = :tenant_id
  AND date_trunc('second', o.observed_at) = timestamptz '2026-10-31 16:59:01+00';
```
Parâmetro `:tenant_id` = id do provedor da bancada (uso em `psql`: `\set tenant_id '…'` e `:'tenant_id'`; a sessão também fixa `app.tenant_id`, o escopo de RLS). Saída agregada da execução de 2026-10-31 (uma linha, colunas na ordem do SELECT): `12 | 5 | 2 | 1 | 1 | 1`, ou seja `onus = 12`, `prefixo_zteg = 5`, `prefixo_alcl = 2`, `instantes = 1`, `pons = 1`, `olts = 1` (uma única PON, de uma única OLT, numa única coleta). A família vem dos 4 primeiros bytes do GPON SN em hex lidos como ASCII. Não há exportação versionada (seriam seriais de ONUs). O resultado vale para esse instante; outra coleta pode ter outros números.
