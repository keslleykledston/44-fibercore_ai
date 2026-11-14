# Deploy da LAB em 2026-11-13: organizações isoladas, ACS por organização e centro de OLT (ADR-0046)

Evidência operacional redigida (sem IP, credencial, serial ou conteúdo de backup). Ordem do responsável no chat ("pode fazer agora"). Estado: **LAB**, nenhum gate de produção concedido. **Flags `fleet_provision`, `fleet_secrets` e `acs_registry` DESLIGADAS** em todos os provedores e `managed_olts` AUSENTE no Edge: nada novo está ativo.

## O que subiu (ordem: Edge, depois nuvem)
- **Edge (host do GenieACS), ~02:57Z:** binário `0.9.0-lab-d983858` (`CGO_ENABLED=0`, linux/amd64, `-trimpath -s -w`), sha256 `adc75fea…5670` conferido no host. Enviado como `fibercore-edge.new`; o atual (`993adf02…`, 0.9.0-lab-f47ae43) ficou em `fibercore-edge.prev`; trocado depois de o log da coleta da OLT ficar estável por 20 s (o `run.sh` aplica o `.new` na partida). `config.json` **inalterada**; 1 processo; "fibercore-edge starting" com a versão nova; heartbeat vivo na nuvem.
- **Nuvem, ~02:58Z:** `main` em `d983858`. Backup lógico antes (`scripts/backup.sh`, `fibercore-prod`): 638 389 bytes, 720 entradas no `pg_restore -l`, sha256 OK (sem a tabela de entregas). `up -d --build migrate api-core outbox-relay event-consumer job-sweeper` e depois `web --no-deps`. `alembic_version` = **0053** (0051 centro de OLT, 0052 ACS, 0053 organizações). Todos `Up (healthy)`; `/api/livez` 200, `/login` 200, `/rede/frota`, `/rede/acs` e `/plataforma/organizacoes` sem sessão 307 (login).
- **Efeito colateral:** o `migrate` depende do NATS e o Compose **recriou o contêiner do NATS** (volume do JetStream preservado). O `event-consumer` registrou uma única rajada de erro de DNS no instante da recriação (02:58:02Z) e voltou sozinho; depois disso nenhum erro. Diferente do deploy anterior, em que o NATS não foi recriado.

## Verificação
- Antes do deploy, em `main`: API 1296 passed; Go `vet` e `test -race` (19 pacotes) ok; `tsc` ok; Playwright `puros` 78 passed; e2e `funcional`+`frota` 93 passed (inclui o formulário único); interoperação real navegador → API → Edge Go: 9 provas PASS (`INTEROP_ADR-0046_2026-11-12.md`).
- LAB depois do deploy: 5 funções `SECURITY DEFINER` novas existem; flags novas ligadas em 0 provedores; logs de 5 min sem erro em `api-core`, `web`, `outbox-relay` e `job-sweeper`.

## Não feito / limites
- Nada testado na LAB com as flags ligadas nem com `managed_olts` no Edge real; nenhuma OLT real tocada (interop usou servidor SSH de teste).
- Riscos R-2 e R-3 do ADR-0046 aceitos pelo responsável ("prossiga"); as flags continuam desligadas até ele mandar ligar.
- Acesso ao host do Edge por senha do `.env` via script que não imprime valores.

## Para usar (responsável)
1. No Edge, seção `managed_olts` com política local (`allowed_cidrs`, `allowed_ports`, `max_olts`, `allowed_vendors`) e `olt_secrets` (`docs/operations/EDGE_MANAGED_OLTS.md`, `EDGE_SECRETS.md`); reiniciar; `fibercore-edge seal-fingerprint`.
2. `feature-set <tenant> fleet_provision on`, `fleet_secrets on` e (ACS) `acs_registry on`; na tela da OLT confirmar a impressão digital da chave do Edge; cadastrar pelo formulário único; no host do Edge rodar `fibercore-edge managed-trust <nome>`.

## Reversão
- Edge: `mv fibercore-edge.prev fibercore-edge` e `pkill -x fibercore-edge` (o cron religa).
- Nuvem: flags já desligadas; `alembic downgrade 0050` desfaz 0053, 0052 e 0051 (apaga os dados dessas tabelas/colunas); restaurar o backup só se necessário.

## Ativação das flags (ordem do responsável: "Faça push e ligue as flags", mesmo dia)
- **Push:** `main` enviada a `origin` (`721727e..fa3cb57`) depois do gitleaks 8.21.2 nos 42 commits novos: no leaks.
- **Edge (host do GenieACS):** backup `config.json.pre-managed`; acrescentadas as seções `olt_secrets` (chave de selagem em `~/fibercore-edge/seal`, 0700) e `managed_olts` com política **conservadora**: `allowed_cidrs` = só a rede /24 da OLT já cadastrada, `allowed_ports` [22], `max_olts` 8 (estáticas incluídas), `allowed_vendors` ["huawei"], `allow_legacy_ssh` false, `pon_ports` iguais às da OLT estática, `state_dir` em `~/fibercore-edge/managed` (0700). `managed-list` validou a configuração antes; reinício com a coleta parada; log: "managed olts enabled", "olt secrets enabled", "seal key published". Chave nova gerada; `key_id` 18cb776972f3972f (impressão digital 18cb-7769-72f3-972f-1802-aa8d-7258-9c84).
- **Nuvem:** `feature-set` do provedor da LAB (K3G Solutions): `fleet_secrets`, `fleet_provision`, `acs_registry` = **on** (conferido em `tenant_features`). Chave do Edge vista pela nuvem: `seal_key_state = pending`. Logs de 1 min sem erro; `/api/livez` e `/login` 200; telas protegidas 307 (login).
- **Falta (humano):** abrir a tela da OLT/Frota, **comparar a impressão digital acima** com a do host do Edge (`fibercore-edge seal-fingerprint`) e confirmar; só então a entrega cifrada é liberada. Depois de cadastrar uma OLT pelo formulário único, rodar `fibercore-edge managed-trust <nome>` no host do Edge (compara a impressão digital do host SSH da OLT). Nenhuma OLT gerenciada foi cadastrada nem confiada.
- **Reversão das flags:** `feature-set <tenant> <flag> off` (via `migrate`, que tem a conexão admin). Edge: restaurar `config.json.pre-managed` e `pkill -x fibercore-edge`.

## Ajuste de interface e conta operadora (mesmo dia, depois da ativação)
- **Layout:** `9bfb77f` (cadastro de OLT compacto: grade, ajuda recolhida, identificação em grade). Só o contêiner `web` foi reconstruído na LAB (`up -d --build --no-deps web`), healthy; API, Edge e flags intactos. Reversão: voltar ao commit anterior (`fa3cb57`/`e93c908`) e repetir o comando.
- **Organizações:** a aba só aparece para conta marcada como operadora da plataforma (`users_global.is_platform_operator`). Por ordem do responsável, `admin@k3gsolutions.com.br` foi marcada com `platform-operator` (via serviço `migrate`); a sessão antiga é invalidada, então é preciso sair e entrar de novo, e criar/listar organizações exige MFA confirmado nos últimos 10 min. Desfazer: `platform-operator --email ... --off`.
- **Conhecido, não corrigido:** o teste e2e `acs.spec.ts:122` (engenheiro só lê) falha também sem estas mudanças: a tela responde "Sem permissão" ao papel `engineer`. Vem de antes deste ajuste; a investigar.

## ADR-0047 fatia A na LAB (ordem do responsável: "Escreva o adr, faça push e aplique")
- **Push:** `main` enviada (`fa3cb57..df256004` em duas levas), gitleaks 8.21.2 sem vazamentos nos commits novos. Revisão Codex da API: r1 `needs-attention` (1 HIGH, 2 MEDIUM, 1 LOW; corrigidos ou aceitos, ver o ADR-0047, bruto `raw/630-org-lifecycle-api-r1.txt`).
- **Aplicado (~06:55Z):** backup lógico antes (`build/backups/fibercore-20261113T065322Z.dump`, 672 705 bytes, com sha256). Imagens reconstruídas; `migrate` rodou sozinho (`--no-deps`, o NATS **não** foi recriado): `alembic_version` 0053 → **0054** (4 funções do operador e a lista com saúde). `up -d --no-deps` de `api-core`, `outbox-relay`, `event-consumer`, `job-sweeper` e `up -d --build --no-deps web`. Todos healthy; `/api/livez` e `/login` 200, telas protegidas 307; 0 erro nos logs de 3 min; K3G Solutions `active`, flags intactas.
- **Testes antes do deploy:** API 1311 passed (Postgres e NATS descartáveis); `tsc` ok; e2e `puros`+`funcional`+`plataforma` 169 passed.
- **O que mudou para o usuário:** organização suspensa responde `403 organization_suspended` a usuário e ao Edge (por requisição; reativar vale na hora). Aba Organizações ganha detalhe, saúde, renomear, suspender/reativar com motivo e flags (as de escrita em rede só desligam; ligar segue pela CLI). Emergência: `org-status <tenant> active|suspended --reason "..."` pelo serviço `migrate`.
- **Não verificado na LAB:** nenhuma organização foi suspensa na LAB (a única é a K3G, em uso); a prova da suspensão é a dos testes. Capturas do how-to ainda faltam (artigo em rascunho).
- **Limites conhecidos:** `service-token` ainda emite token para organização suspensa (não dá acesso); usuário de organização suspensa que ainda não ativou o MFA exigido vê primeiro a tela de ativar MFA; axe no escuro do item ativo do menu (já existia).
- **Reversão:** reativar a organização (tela ou CLI); `alembic downgrade 0053` remove as funções; imagens anteriores por `git checkout` + rebuild.

## ADR-0047 fatias B a F + 6 organizações de clientes na LAB (ordem do responsável: "prossiga", 2026-11-14)
- **Backup antes:** `build/backups/fibercore-20261114T152101Z.dump` (709 057 bytes, com sha256). **Não pushado** (só commits locais, último `7c119de2`).
- **Aplicado:** imagens novas, `migrate` sozinho (`--no-deps`, NATS **não** recriado): alembic 0054 → **0061** (limites, fila de e-mail, política de MFA, escopo, encerramento, tokens de API, webhooks); `up -d --no-deps` de `api-core`, `outbox-relay`, `event-consumer`, `job-sweeper` e dos **serviços novos `mailer` e `webhooks`** (ambos healthy, **ociosos**: sem `FIBERCORE_SMTP_*`/`FIBERCORE_PUBLIC_BASE_URL` e sem `FIBERCORE_WEBHOOK_ENCRYPTION_KEY` e-mail e webhook não existem); `web` reconstruído. `/api/livez` e `/login` 200; 0 erro nos logs.
- **Organizações criadas (CLI do dono):** WA TELECOM, FW NETWORK, GL CONNECT, ARAUJO, JGA, ASANET; cada uma com 1 Edge **placeholder** (`edge-pendente-N`, sem agente), flag `fleet_manager` ligada e `admin@k3gsolutions.com.br` como `isp_admin` (aparece no seletor de organização).
- **10 OLTs cadastradas só com metadados** (nome, fabricante, endereço, porta, protocolo, site = nome do cliente; **nenhuma credencial** entrou na plataforma). VSOL (WA TELECOM) marcada "CONFIRMAR PORTA" (repete IP e porta da DATACOM2); as 2 da FW NETWORK marcadas inalcançáveis do servidor.
- **Separação provada ao vivo** com um usuário por organização (engenheiro, depois desativados): cada um lista só as OLTs da sua organização (3/2/1/2/1/1), `GET` por id de OLT alheia dá 404 (0 vazamentos) e trocar `X-Workspace-Id` para outra organização dá 404.
- **Teste de conexão pela plataforma:** `409 olt_query_disabled` (flag desligada e sem Edge nessas organizações) e `422 protocol_not_supported` para Telnet. **Não ligadas** flags de operação em rede: decisão do dono.
- **Captura real somente leitura (fora da plataforma):** `docs/wiki/bench/H1-captura-multivendor-clientes-2026-11-14.md`.
- **Reversão:** reativar/encerrar organizações pelo fluxo do ADR-0050; `alembic downgrade 0054` remove os recursos novos; imagens anteriores por `git checkout` + rebuild; restaurar o backup só se necessário.
