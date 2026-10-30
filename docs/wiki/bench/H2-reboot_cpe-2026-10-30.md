# Evidência de manobra de bancada — H2 `reboot_cpe` — 2026-10-30

Escopo: SOMENTE a ONT de bancada (Huawei EG8145V5, firmware V5R019C10S350). Sem credencial, IP, nome de cliente ou saída crua.

- **Hash da intenção:** `7b7a9283944695e543b5a64f37f52a45383df3c59975534b78033e07bc10417b` (job `c6ed9338-32af-4126-b7b9-0321996b8550`, operação `reboot_cpe`, sem parâmetros)
- **Identidades observadas:** antes da manobra o Edge releu no ACS exatamente 1 documento com OUI `00259E`, classe `EG8145V5`, serial `48575443E2247AA5` (igual à lista local do Edge e à de bancada da nuvem); a ONU correspondente está na posição `0/0/14` da OLT, vínculo ONU↔CPE `confirmed` (H1: `docs/wiki/bench/H1-identificacao-2026-10-30.md`)
- **Estado antes:** `_lastBoot` do ACS = 2026-10-29T22:27:35Z; WAN link Up e PPP Connected (cpe_state); ONU online na OLT; nenhuma tarefa pendente na ONT; o ACS não tinha nenhuma tarefa `reboot` (conferido pelo Edge antes do envio)
- **Estado depois:** `_lastBoot` do ACS = 2026-10-30T03:32:41Z (um único dispositivo do ACS com boot novo desde as 03:20: a ONT de bancada; os demais 37 não mudaram); nenhuma tarefa `reboot` ficou no ACS; claim no Edge `DONE`; autorização `consumed`; alvo sem trava de escrita; job `SUCCEEDED` com pós-checagem. Lado OLT: ver "Observação da OLT" abaixo.
- **Resultado da restauração:** não há estado a restaurar num reboot; o retorno foi OBSERVADO pelo novo boot informado ao ACS (`_lastBoot` posterior ao envio) e pela pós-checagem do Edge
- **Versões:** Edge `0.5.1-lab-6816ed1`; firmware do CPE `V5R019C10S350`; OLT Huawei MA5608T, firmware MA5600V800R015
- **Aprovador:** o próprio solicitante, conta de serviço `isp_admin` de ensaio (`lab-bench-h2-…`, emenda "aprovação da bancada" do ADR-0030); autorização prévia `d50df127-b207-4c34-a152-c38fbdcb8986` registrada pelo responsável no owner CLI (`--first-run`, janela 03:30:49–03:45:49 UTC; o campo `--by` foi gravado com o texto de exemplo, sem nome)
- **Horário:** aprovação 2026-10-30 03:31:28 UTC; despacho 03:31:38; boot da ONT 03:32:41; job `SUCCEEDED` 03:32:48 (tudo em UTC)
- **Aceite do responsável:** dado em 2026-10-30 pelo chat da sessão ("aceito o resultado do H2")

## Observação da OLT
A coleta da OLT que começou às 03:30:31 UTC e terminou às 03:33:07 registrou a ONU `offline`: ela leu a ONU durante a reinicialização. A volta da ONU a `online` foi OBSERVADA pelo responsável na OLT logo após o reboot (~03:33 UTC, relato no chat da sessão); a coleta automática seguinte da nuvem (~03:48 UTC) ainda é registrada abaixo quando chegar.
