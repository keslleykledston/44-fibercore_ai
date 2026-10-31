# H1 — identificação (SOMENTE LEITURA) — ZTE F670L — 2026-10-31

Escopo: leitura. **Nenhuma manobra, nenhuma escrita, nenhum registro de alvo de bancada.** Sem credencial, IP ou dado de cliente.

| Item | Observado |
|---|---|
| CPE no ACS | dispositivo ZTE F670L (OUI `FC4009`, serial TR-069 terminado em `…9122`); 1 único dispositivo ZTE no ACS; Inform e boot recentes após o reinício manual feito pelo responsável |
| CPE na nuvem | ingerido (fabricante ZTE, modelo F670L); firmware ainda não lido; **sem vínculo ONU↔CPE** |
| ONU na OLT | GPON SN terminado em `…A1A3` (prefixo ASCII `ZTEG`, o informado pelo responsável), PON `0/0/14`, online, RX −14,81 dBm |
| Vínculo CPE↔ONU | **NÃO confirmado.** O serial TR-069 (`…9122`) não é o GPON SN (`…A1A3`): formatos diferentes, então não há igualdade de serial como na Huawei |
| Contexto da PON | `0/0/14` tem 12 ONUs na coleta de 2026-10-31 (5 com prefixo da família ZTE). Só as ONUs de bancada conhecidas estão na lista de bancada; a natureza das demais (cliente ou outra) **não foi verificada**, então a PON deve ser tratada como NÃO exclusiva da bancada, com possível tráfego de produção |
| Reboot do responsável | a coleta da OLT (15 min) não viu a ONU offline, então os horários não corroboram o vínculo |

## Para confirmar o vínculo (precisa do responsável)
Uma destas, com a evidência anexada aqui: (a) leitura do GPON SN no próprio CPE (etiqueta física ou parâmetro do fabricante lido por caminho autorizado); (b) reinício acompanhado com a ONU observada offline→online na OLT e o novo boot no ACS na mesma janela (exige coleta com intervalo menor, sob autorização para a OLT real).

## Pendente antes de qualquer alvo de bancada
Emenda do ADR-0030 (lista fechada com mais de um modelo), autorização do responsável para ESTA identidade, `bench-target-add`, entrada na lista local do Edge e registro de capacidades por fabricante/modelo/firmware.
