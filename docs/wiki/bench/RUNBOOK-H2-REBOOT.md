# Runbook do responsável — H2 `reboot_cpe` na ONT de bancada (ADR-0030)

Escopo: SOMENTE a ONT de bancada. Nada aqui toca CPE/ONU de cliente. Sem credencial, IP ou serial neste arquivo: os valores reais ficam na configuração do Edge e no banco.

## Pré-condições (todas, em ordem)
1. Edge novo (com `agents/edge/internal/bench`) instalado no host do Edge; configuração com a seção `bench` (lista local com `oui`, `product_class`, `serial` da bancada), `bench_writes_enabled: true`, `jobs_enabled: true`, `nbi_url` e `"reboot_cpe"` em `allowed_operations`. Sem a seção, o Edge recusa o envelope.
2. Backup da nuvem (`scripts/backup.sh`) e migração 0021 aplicada.
3. Firmware do CPE gravado na nuvem (o registro de capacidades casa por firmware exato).
4. Owner CLI (na nuvem): `bench-target-add` (CPE da bancada), `feature-set <tenant> bench_writes on`, entrada de capacidade `supported` + `identified` com evidência (perfil exato, firmware incluído) e, **imediatamente antes da manobra**, `bench-authorize reboot_cpe <cpe> --from <agora> --to <agora+15min> --by <responsável> --first-run` (a primeira execução; depois dela a evidência promove a entrada a `observed` e as próximas autorizações dispensam `--first-run`).
5. Responsável presente, com a ONT de bancada em condição de ser reiniciada (sem cliente dependendo dela).

## Execução
1. Solicitante cria o job `reboot_cpe` (preview → submit); um `isp_admin` distinto aprova (a aprovação consome a autorização).
2. O Edge confirma identidade no ACS, reserva o ritmo, grava o claim e envia UMA tarefa `reboot`. Aguarda até 4 min por novo `_lastBoot`.
3. Resultado: `SUCCEEDED` (voltou) ou `UNKNOWN`/`FAILED` (alvo travado; ver abaixo).

## Se algo sair do esperado
- Alvo travado (`write_locked`): olhar o ACS (tarefa `reboot` pendente? CPE online?) e só então `bench-unlock`.
- Claim UNKNOWN no Edge: a autorização está gasta; peça outra. Nunca edite o arquivo de claims.
- Tarefa `reboot` que ficou no ACS: remover pelo ACS (uma só, a do dispositivo de bancada) antes de nova tentativa.

## Evidência
Copiar `TEMPLATE.md` para `H2-reboot_cpe-<data>.md`, preencher e só então `capability-set --evidence-file` (promove a `observed`).
