# Runbook do responsável — H3 `set_wifi_ssid` na ONT de bancada (ADR-0030)

Escopo: SOMENTE o rádio 2,4 GHz (`WLANConfiguration.1`) da ONT de bancada. O SSID de teste tem de casar `^BANCADA-[A-Z0-9]{1,16}$`. O Edge lê o SSID atual, grava o novo, lê de volta, **restaura o original e lê de volta**; o original fica só no host do Edge (`bench-restore.json`, modo 0600) até a restauração ser confirmada. Nenhuma senha de Wi-Fi é lida ou escrita. Os clientes ligados ao Wi-Fi da ONT de bancada perdem a conexão por alguns segundos.

## Pré-condições
1. Edge com `"set_wifi_ssid"` em `allowed_operations` (além de `reboot_cpe`) e a seção `bench` já usada no H2.
2. Registro: `capability-set <tenant> "Huawei Technologies Co., Ltd" EG8145V5 V5R019C10S350 tr069 set_wifi_ssid supported identified --evidence <arquivo H1/H3> --verified-at <agora>`.
3. Migrações até a 0022 e API com o PR do H3.

## Autorização (a sua, por manobra; o SSID faz parte dela)
```
$C bench-authorize <tenant> set_wifi_ssid <cpe> --from "<agora>" --to "<agora+15min>" --by "Seu Nome" --ssid BANCADA-H3 [--first-run]
```
`--first-run` só na primeira execução (enquanto não existe entrada `observed`). Respeite o intervalo de 30 min entre manobras na mesma ONT (o ritmo do Edge é por dispositivo).

## Execução
Job `set_wifi_ssid` com `params: {"ssid": "BANCADA-H3"}` (preview → submit → approve pelo próprio solicitante). Resultado `SUCCEEDED` = mudou, leu de volta, restaurou e leu de volta. `FAILED`/`UNKNOWN` = alvo travado; se o detalhe disser que a restauração não foi confirmada, restaure o SSID original (arquivo `bench-restore.json` no host do Edge) antes de `bench-unlock`. **Antes de qualquer `bench-unlock` depois de um H3 com falha, confira no ACS que não resta nenhuma tarefa `setParameterValues`/`reboot` do dispositivo de bancada** (`GET /tasks?query={"device":"<id>"}` no host do ACS): uma tarefa enfileirada dispara quando a ONT se conecta. O Edge já remove as próprias tarefas e recusa nova manobra enquanto existir uma pendente, mas o `bench-unlock` roda na nuvem e não enxerga o ACS.

## Evidência
`TEMPLATE.md` → `H3-set_wifi_ssid-<data>.md` → `capability-set ... observed --evidence-file`.
