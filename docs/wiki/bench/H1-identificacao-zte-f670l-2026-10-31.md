# H1 — identificação (SOMENTE LEITURA) — ZTE F670L — 2026-10-31

Escopo: leitura. **Nenhuma manobra, nenhuma escrita, nenhum registro de alvo de bancada.** Sem credencial, IP ou dado de cliente.

| Item | Observado |
|---|---|
| CPE no ACS | dispositivo ZTE F670L (OUI `FC4009`, serial TR-069 terminado em `…9122`); 1 único dispositivo ZTE no ACS; Inform e boot recentes após o reinício manual feito pelo responsável |
| CPE na nuvem | ingerido (fabricante ZTE, modelo F670L); firmware ainda não lido; **sem vínculo ONU↔CPE** |
| ONU na OLT | GPON SN terminado em `…A1A3` (prefixo ASCII `ZTEG`, o informado pelo responsável), PON `0/0/14`, online, RX −14,81 dBm |
| Vínculo CPE↔ONU | **NÃO confirmado.** O serial TR-069 (`…9122`) não é o GPON SN (`…A1A3`): formatos diferentes, então não há igualdade de serial como na Huawei |
| Contexto da PON | `0/0/14` tem 12 ONUs na coleta de 2026-10-31 16:59 UTC (5 com prefixo da família ZTE). Só as ONUs de bancada conhecidas estão na lista de bancada; a natureza das demais (cliente ou outra) **não foi verificada**, então a PON deve ser tratada como NÃO exclusiva da bancada, com possível tráfego de produção |
| Reboot do responsável | a coleta da OLT (15 min) não viu a ONU offline, então os horários não corroboram o vínculo |

## Para confirmar o vínculo (precisa do responsável)
Uma destas, com a evidência anexada aqui: (a) leitura do GPON SN no próprio CPE (etiqueta física ou parâmetro do fabricante lido por caminho autorizado); (b) reinício acompanhado com a ONU observada offline→online na OLT e o novo boot no ACS na mesma janela (exige coleta com intervalo menor, sob autorização para a OLT real).

## Pendente antes de qualquer alvo de bancada
Emenda do ADR-0030 (lista fechada com mais de um modelo), autorização do responsável para ESTA identidade, `bench-target-add`, entrada na lista local do Edge e registro de capacidades por fabricante/modelo/firmware.

## Fonte dos números da PON
Consulta somente leitura ao banco da nuvem do LAB (escopo do provedor da bancada), com o instante da coleta de OLT escolhido **explicitamente** (2026-10-31 16:59:01 UTC):
```sql
SELECT count(*) AS onus,
       count(*) FILTER (WHERE o.serial LIKE '5A544547%') AS prefixo_zteg,
       count(*) FILTER (WHERE o.serial LIKE '414C434C%') AS prefixo_alcl,
       count(DISTINCT o.observed_at) AS instantes, count(DISTINCT o.pon_id) AS pons, count(DISTINCT o.olt_id) AS olts
FROM onus o JOIN pon_ports p ON p.id = o.pon_id AND p.tenant_id = o.tenant_id AND p.olt_id = o.olt_id
WHERE p.pon_path = '0/0/14' AND o.tenant_id = :'tenant_id'
  AND date_trunc('second', o.observed_at) = timestamptz '2026-10-31 16:59:01+00';
```
Parâmetro `:tenant_id` = id do provedor da bancada (uso em `psql`: `\set tenant_id '…'` e `:'tenant_id'`; a sessão também fixa `app.tenant_id`, o escopo de RLS). Saída agregada da execução de 2026-10-31 (uma linha, colunas na ordem do SELECT): `12 | 5 | 2 | 1 | 1 | 1`, ou seja `onus = 12`, `prefixo_zteg = 5`, `prefixo_alcl = 2`, `instantes = 1`, `pons = 1`, `olts = 1` (uma única PON, de uma única OLT, numa única coleta). A família vem dos 4 primeiros bytes do GPON SN em hex lidos como ASCII. Não há exportação versionada (seriam seriais de ONUs). O resultado vale para esse instante; outra coleta pode ter outros números.
