# Evidência de manobra de bancada — H3 `set_wifi_ssid` — 2026-10-30

Escopo: SOMENTE o rádio 2,4 GHz (`WLANConfiguration.1`) da ONT de bancada (Huawei EG8145V5, firmware V5R019C10S350). Sem credencial, IP, nome de cliente ou saída crua. O SSID original ficou só no host do Edge.

- **Hash da intenção:** `2f321573deec51ce1eb76b981342370ad559dd30d9b9b4f6c0a04f60971332ee` (job `7b050c8f-9817-41ae-a772-63f37e1c05a1`, operação `set_wifi_ssid`, parâmetro `ssid = BANCADA-H3`)
- **Identidades observadas:** o Edge releu no ACS exatamente 1 documento com OUI `00259E`, classe `EG8145V5`, serial `48575443E2247AA5` (igual à lista local do Edge e à de bancada da nuvem); ONU correspondente em `0/0/14` na OLT (H1: `docs/wiki/bench/H1-identificacao-2026-10-30.md`)
- **Estado antes:** SSID do 2,4 GHz e do 5 GHz de fábrica (o do 2,4 GHz lido pelo Edge antes da troca e guardado só no host); nenhuma tarefa pendente de bancada na ONT; nenhum cliente usando o Wi-Fi (confirmado pelo responsável)
- **Estado depois:** SSID do 2,4 GHz e do 5 GHz iguais aos de antes da manobra (conferidos no ACS depois); 5 requisições ao NBI, todas ao dispositivo de bancada (ler, trocar para `BANCADA-H3`, ler, restaurar, ler); nenhuma tarefa de bancada restante; arquivo de restauração removido; claim `DONE`; autorização `consumed`; as 3 tarefas pendentes que o ACS tem são antigas e de outros dispositivos (julho/16-out), não tocadas
- **Resultado da restauração:** o Edge gravou o valor original em disco antes de mudar, trocou uma vez, leu `BANCADA-H3` de volta, restaurou o original e leu o original de volta; conferido por fora no ACS
- **Versões:** Edge `0.6.1-lab-` (PR 62); firmware do CPE `V5R019C10S350`; OLT Huawei MA5608T, firmware MA5600V800R015
- **Aprovador:** o próprio solicitante, conta de serviço `isp_admin` de ensaio (`lab-bench-h3-…`, emenda "aprovação da bancada" do ADR-0030); autorização prévia `6833fa43-28a5-409b-99f0-ab2b1f6ac2a9` registrada pelo responsável (`--first-run`, `--ssid BANCADA-H3`, janela 05:12:21–05:27:21 UTC)
- **Horário:** aprovação ~05:12:49 UTC, despacho 05:12:49, requisições ao NBI 05:12:46–05:12:50, job `SUCCEEDED` 05:12:59 (UTC). Uma tentativa anterior (job `121d1ad6-…`, 04:55) foi recusada antes de qualquer escrita porque a credencial de Connection Request da ONT estava desalinhada do ACS; realinhada pelo responsável.
- **Aceite do responsável:** dado em 2026-10-30 pelo chat da sessão ("aceito"), sobre o resultado do H3 acima
