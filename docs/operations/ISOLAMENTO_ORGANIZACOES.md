# Isolamento entre organizações: evidência (ADR-0046 D1)

Organização = tenant. Esta página registra **o que foi provado** com duas organizações reais (`apps/api/tests/test_org_isolation.py`) e **o que não foi**. Não é certificação: é o que o teste executa, hoje.

## Como foi montado
- As duas organizações **nascem pelo caminho da tela**: conta operadora com MFA recente → `POST /v1/platform/organizations` → função `platform_create_organization` → convite do primeiro administrador **aceito** → administrador entra. Nada de `INSERT` direto em `tenants`.
- Cada uma recebe: um Edge com conta de serviço; uma OLT lida pelo Edge (2 ONUs); uma OLT cadastrada na tela (com POP, SSH, impressão digital); um CPE; chave de selagem publicada pelo Edge e **confirmada por pessoa**; uma entrega de credencial (`ssh_login`) e uma de conexão (`olt_connection`); um convite pendente; um segundo membro; flags próprias **diferentes** (`onu_discovery` só numa, `profile_studio` só na outra); trilha de auditoria.
- **Impressões digitais:** todo UUID e todo rótulo (nome, serial, e-mail; todos levam uma marca única da organização) de CADA organização, lidos como dono do banco. Uma resposta à outra organização nunca pode conter nenhum (35 identificadores por organização, depois de tirar os compartilhados, como a conta operadora que criou as duas).
- **Resumo MD5 de toda tabela com `tenant_id`** de uma organização antes e depois de cada ataque da outra: qualquer mudança, em qualquer tabela, derruba o teste.
- **Controle negativo** (`test_negative_control_…`): planta uma política que deixa a role da aplicação ler os POPs de todas as organizações e mostra que as MESMAS verificações (varredura de listas, varredura de banco) a detectam; a política é removida no `finally`. Sem isso, "passou" não diria nada.

## O que é provado (nos dois sentidos, A→B e B→A)
| Recurso | Prova | Teste |
|---|---|---|
| Listas (OLT, ONU, POP, Edge, CPE, membros, convites, auditoria, flags, entregas) | contêm só o que é da organização; **contagens** iguais às do banco para ela (olts 2, onus 2, cpes 1, pops 1, edges 1, membros 2); flags `source=tenant` com os valores dela | `test_counts_and_lists_are_the_organizations_own` |
| Todas as rotas GET sem parâmetro do inventário RBAC (39 por sentido, com o administrador e com o Edge) | nenhuma resposta traz identificador ou rótulo da outra | `test_every_parameterless_get_route_never_shows_the_other_organization` |
| Detalhe por id (OLT, ONU, CPE, Edge, POP, entrega, membro, convite; 34 sondagens por sentido) | o id da outra organização responde **igual** (status e corpo, com o id normalizado) a um id que não existe: 404 idêntico, sem diferença de cabeçalho ou texto | `test_get_by_id_of_the_other_organization_is_the_same_404_as_an_unknown_id` |
| `X-Workspace-ID` da outra organização | 404 idêntico ao de um workspace inexistente, em leitura e em escrita | `test_the_other_organizations_workspace_header_…` |
| Escritas sobre objeto da outra (16 por sentido: POP, OLT, conexão, entrega de segredo/conexão, confirmar chave do Edge, convite, renovar, reset de senha, remover, trocar papel, sincronizar ONUs…) | resposta igual à de objeto inexistente (403/404/422, nunca sucesso); **a outra não muda em nenhuma tabela**; a própria só ganha, no máximo, a auditoria da recusa | `test_writes_against_the_other_organization_…` |
| `tenant_id` no corpo, no cabeçalho ou na consulta | corpo com `tenant_id`/`org_id` → 422 (campo desconhecido, nunca obedecido); cabeçalhos `X-Tenant-Id`, `X-Tenant`, `X-Org-Id`, `Tenant-Id` e `?tenant_id=` → mesma resposta de antes; o objeto criado vai para a organização do chamador | `test_tenant_id_in_body_header_or_query_is_ignored_or_refused` |
| Token de Edge de uma organização | não escreve na outra: snapshots de OLT/CPE com o `edge_id` dela → 403; `result` de entrega dela → 404 igual ao de id inexistente; `managed-olts/state` com a OLT dela → `ignored` (indistinguível de id inexistente); `jobs/{id}/result`; cabeçalho `X-Workspace-ID` com a outra não muda nada para token de serviço; token de Edge não abre rota de pessoa e vice-versa | `test_an_edge_token_of_one_organization_cannot_write_in_the_other` |
| Token trocado | conta de serviço de uma com `tid` da outra → 401 (assinatura válida, vínculo falso); assinado por outra chave → 401 | `test_a_service_token_naming_another_tenant_…` |
| Entregas de segredo/conexão | o `next` do Edge de uma devolve só a entrega dela; a linha da outra não se mexe; uma chave nova de um Edge cancela só as entregas dele | `…delivery_is_never_handed…`, `test_zz_an_edge_publishing_a_seal_key_…` |
| Convites e membros | convite de B só coloca quem o tem em B (e a pessoa não enxerga A: 404); administrador de A recebe 404 ao ler/alterar o time de B | `test_invites_and_members_…` |
| Banco, role da aplicação, **49 tabelas** com `tenant_id` | todas com RLS **ligada e forçada** e ao menos uma política; em 48 delas (as que a role pode ler) `SELECT` de linha de outra organização = 0, com e sem tenant escolhido; `INSERT` com `tenant_id` da outra em `audit_log`/`events_outbox` → 42501; `UPDATE`/`DELETE` em linha da outra afeta 0 linhas ou nem é permitido (a maioria das tabelas não dá `UPDATE`/`DELETE` à role); `tenants` mostra só a própria linha; `INSERT` em `tenant_features`/`member_invites` da outra → sem privilégio | `test_every_table_with_a_tenant_…`, `test_the_application_role_…` (3) |
| Blob de entrega | a role da aplicação não lê a coluna `sealed` (nem a da própria organização); só o dono do banco | `test_the_other_organizations_blob_…` |
| Visão entre organizações | só a lista de plataforma (`GET /v1/platform/organizations`), que exige conta operadora ativa + MFA recente e devolve **rótulos e contagens**: nenhum serial, e-mail, endereço, nome ou id de OLT/ONU/Edge; 403 para o `isp_admin` de qualquer organização | `test_the_platform_list_is_the_only_cross_organization_view_…` |

## O que NÃO é provado (limites declarados)
1. **Variáveis de sessão forjáveis** (`app.tenant_id`, `app.user_id`): quem executa SQL arbitrário com a role da aplicação ou controla o processo da API escolhe o tenant. É a fronteira de confiança do projeto inteiro (ADR-0031 pergunta 7; ADR-0046 D1, R-3). Aqui a RLS é provada contra a **API** e contra a role **sem** forjar contexto.
2. **`users_global` não tem `tenant_id`** (uma conta pode estar em várias organizações): a role da aplicação lê a tabela inteira por SQL direto. A API nunca a devolve sem passar por pertencimento (listas de equipe fazem `JOIN` com a membership da organização).
3. **Delegação da plataforma** (ADR-0031) é a porta legítima entre organizações: 8 h, com motivo, só para operador, escopo `tenant:read`. Fora desta suíte (tem a sua).
4. **Rotas por identificador sem objeto neste mundo** (16 rotas GET: jobs, incidentes, execuções de diagnóstico, rascunhos de profile, snapshots, conexões de ERP, clientes…): não há objeto delas nas duas organizações aqui; ficam cobertas pela varredura de banco (todas as tabelas), pelas suítes próprias de cada módulo e pelo teste de inventário RBAC. Lista exata impressa por `-s` (`ISOLATION-COVERAGE`).
5. **Contas de serviço e RBAC de papéis** (o que cada papel pode ver dentro da própria organização) não é isolamento entre organizações: ver `test_rbac_inventory.py`.
6. Concorrência entre organizações (carga) e canais laterais (tempo de resposta) não foram medidos.

## Como repetir
```bash
TEST_PG_PORT=<porta livre> TEST_NATS_PORT=<porta livre> PYTHON=.venv/bin/python scripts/test-env.sh start
TEST_PG_PORT=<porta> TEST_NATS_PORT=<porta> PYTHON=.venv/bin/python scripts/test-env.sh run -s tests/test_org_isolation.py   # imprime ISOLATION-COVERAGE
TEST_PG_PORT=<porta> TEST_NATS_PORT=<porta> scripts/test-env.sh stop
```
O teste nasce das duas organizações pela função de plataforma; se a criação pela tela quebrar, ele quebra também.
