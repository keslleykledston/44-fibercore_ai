# ADR-0047: Ciclo de vida da organização, console do operador e roadmap multi-organização (sem revenda, sem cobrança)

Status: Accepted e construídas as **fatias A** (D1 e D2), **B** (D3), **C** (D4, ADR-0048) **D** (D5 e D6, ADR-0049), **E** (ADR-0050) e **F** parcial (F1 tokens e F2 webhooks, ADR-0051); **Proposed** só o SSO (F3), que exigem ADR ou emenda própria antes da construção | Data: 2026-11-13 | Owner: Claude Code (implementação), Codex (revisão)

Origem: levantamento de lacunas multi-organização (2026-11-13) e decisões do responsável no mesmo dia: **revenda NÃO; cobrança NÃO (por enquanto)**; ordem "escreva o ADR, faça push e aplique". Estende o ADR-0046 D1 (organização como limite de isolamento, criada por operador da plataforma) e fecha o que ele deixou "fora desta fatia" (suspensão de organização pela tela). Não altera o ADR-0031 (RBAC); a fatia D só o reabre.

## Contexto

Fatos do código (verificados em 2026-11-13):
- **Organização = tenant**, RLS forçada, criada pela tela do operador (`is_platform_operator`, MFA recente, função `SECURITY DEFINER`, migração 0053). Existe isolamento provado por suíte de duas organizações.
- **`tenants.status` já existe** (`active|suspended`, migração 0001), mas **nada o impõe**: só a lista de workspaces do usuário filtra `status = 'active'`. Uma organização "suspensa" continua autenticando, ingerindo do Edge e executando jobs. Suspender é hoje "do dono (CLI)" e, na prática, não faz nada.
- **Flags por organização** (`tenant_features`, 24 recursos) só mudam pela CLI do dono (`feature-set`), que recusa `bench_writes` e `olt_query` enquanto o suporte do Edge não existe.
- **Console do operador**: a lista (`platform_list_organizations`) mostra nome, estado, nº de Edges, OLTs e ONUs, criador e estado do convite. Não mostra saúde (Edge sem heartbeat, OLT sem coleta) nem as flags.
- Sem planos, cotas, faturamento, e-mail, SSO, tokens de API, webhooks ou white-label (zero no código).

## Decisão

### D0 — Fora de escopo (decisão do responsável)
- **Revenda / hierarquia de organizações: NÃO.** O modelo continua plano (uma organização não tem mãe nem filhas). Nenhuma coluna, rota ou tela prepara isso.
- **Cobrança, planos comerciais e medição para faturamento: NÃO, por enquanto.** Revisitar só por ADR próprio. Limites técnicos de proteção (D3) **não** são planos.

### D1 — Suspender, reativar e renomear organização, com imposição real (fatia A)
- **Imposição por requisição.** `get_principal` passa a recusar com **403 `organization_suspended`** qualquer chamada (usuário **e** conta de serviço do Edge) cuja organização selecionada tenha `status <> 'active'`, **depois** de resolver a organização e **antes** de devolver o principal (a checagem lê `tenants` na mesma conexão; sem cache, então a reativação vale na hora). Consequências: login continua possível (o usuário vê o estado), mas nada de `/v1` da organização responde; o Edge recebe 403 e retém a fila local, retomando sozinho ao reativar; nenhum token precisa ser revogado. A lista de workspaces já esconde a organização suspensa; passa a trazer `suspended` para o usuário ver o motivo "organização suspensa" em vez de um erro mudo.
- **Workspaces:** `GET /v1/auth/workspaces` passa a listar a organização suspensa com `suspended: true` (antes a escondia), para a pessoa ver o porquê.
- **Quem pode:** só operador da plataforma, conta ativa, **MFA recente**, permissão `platform:organizations`, por **funções `SECURITY DEFINER`** no mesmo padrão da 0053 (dona = dona do esquema, `search_path` fixo, `REVOKE ALL FROM PUBLIC`, `GRANT EXECUTE` só à role da aplicação, ator rechecado dentro da função): `platform_set_organization_status(p_actor, p_tenant, p_status, p_reason, p_request)` e `platform_rename_organization(p_actor, p_tenant, p_name, p_request)`. A role da aplicação **não** ganha `UPDATE` em `tenants`.
- **Motivo obrigatório** (3 a 200 caracteres, texto livre sem dado de cliente) para suspender e reativar. **Idempotência:** suspender uma suspensa (ou reativar uma ativa) responde `200` com `changed:false` e não grava auditoria nova. Organização inexistente: `404` sem revelar nada além disso.
- **Auditoria em par** (padrão 0053): a função grava `platform.organization.suspended|reactivated|renamed` (e `platform.feature.set`) na trilha **da organização** (`actor_id` = operador, motivo, `request_id`, de/para) e a rota grava `platform.change.requested` no mesmo `request_id`. A métrica `fibercore_organizations_without_api_trail` **não** foi estendida nesta fatia (o par é gravado e testado; detectar chamada fora da rota por métrica fica como melhoria).
- **Rename:** o nome segue as regras de 2 a 60 caracteres e unicidade (sem diferenciar caixa) da criação. O `id` é imutável.
- **O que a suspensão NÃO faz:** não apaga nem altera dado; não derruba conexões já abertas além do próximo pedido; não para workers internos (relay, sweeper) que só movem o que já existe; não desativa contas. Jobs em andamento terminam por TTL/sweeper, porque o Edge deixa de puxar trabalho.
- **Encerrar organização (exportar e apagar, LGPD): FORA desta fatia** (fatia E). Exige ADR próprio (formato e assinatura do pacote, janela de retenção, irreversibilidade, o que acontece com a trilha de auditoria).
- **Reserva de segurança (quebra-vidro):** CLI `org-status <tenant> active|suspended --reason …` do dono, para o caso de nenhum operador conseguir entrar (o dono do banco escreve direto, sem a função: ator nulo e origem `cli` na evidência, com `request_id` e o mesmo evento do outbox).

### D2 — Console do operador: saúde, flags e histórico por organização (fatia A)
- **Lista** (`/plataforma/organizacoes`): ganha por organização `edges_online` e `edges_total` (regra de heartbeat já usada em `/v1/edges`), `olts_stale` (OLTs sem coleta dentro de 2 ciclos), `last_heartbeat_at`, `flags_on` (contagem) e o estado (`active|suspended`) com o botão de suspender/reativar. **Somente contagens e rótulos**: nunca linha de cliente final, assinante, ONU, serial, endereço ou nome de OLT.
- **Detalhe** (`/plataforma/organizacoes/{id}`): estado e histórico de mudanças de estado/nome/flags (da trilha de auditoria, só ações `platform.*`), tabela de flags da organização (nome, padrão, valor atual, origem `default|tenant`) com ligar, desligar e "voltar ao padrão".
- **Flags pela tela:** função `platform_set_feature(p_actor, p_tenant, p_feature, p_state, p_reason, p_request)` (`SECURITY DEFINER`, mesmas travas, motivo obrigatório, auditoria em par `platform.feature.set`). O nome da flag é validado **no código** contra `FEATURES` (a função não conhece o catálogo; a rota é o único caminho e recusa nome desconhecido com `422`). **Duas listas no código:**
  - `OWNER_ONLY_FEATURES` = flags de **escrita em rede ou de IA**: `bench_writes`, `smart_diagnostics_active_tests`, `smart_diagnostics_remediation`, `quality_active_tests`, `smart_diagnostics_copilot`. A tela **mostra** o valor e **nunca** liga (pode **desligar** ou voltar ao padrão, que é desligado); quem liga é a CLI do dono (como hoje). Tentar ligar por API: `403 owner_only_feature`. A lista também vive na função do banco (Codex r1, HIGH): chamada direta para ligar uma delas é recusada (`owner_only_feature`); um teste compara as duas listas. O que o R-3 ainda permite é escolher `p_actor` entre os operadores.
  - Pré-condições do código (hoje `bench_writes` e `olt_query` dependem de `EDGE_SUPPORT`) valem **também** pela tela, com a mesma mensagem da CLI. As flags de pré-requisito de operação (`fleet_provision` exige `managed_olts` no Edge, `acs_registry` exige `nbi_cloud_id`) só ganham **aviso** na tela (a nuvem não enxerga a configuração local do Edge).
- **Permissões:** `platform:organizations` cobre ler e agir (R3, nenhum papel de organização a tem). Leitura da lista/detalhe exige conta operadora ativa; **agir exige MFA recente**.
- **Sem acesso a dados da organização:** o console não vira porta lateral. Entrar numa organização continua sendo só por membro real ou por delegação com prazo (ADR-0031 item 5).

### D3 — Limites técnicos por organização, sem plano nem preço (fatia B, **Accepted e construída**, migração 0055)
Tabela `tenant_limits (tenant_id PK, max_edges, max_olts, max_members, ingest_per_minute, ingest_burst, updated_by, updated_at)`; **coluna NULL = padrão do código** (`Settings`: 25 Edges, 250 OLTs, 200 membros, ingestão da organização 300 de rajada e 1200/min), então a linha só existe quando o operador ajustou algo. A role da aplicação só **lê** (política por organização); o único caminho de escrita é `platform_set_limits` (mesmo contrato da 0054: `SECURITY DEFINER`, `platform_assert_actor`, motivo, `request_id`, faixas validadas no banco, idempotente, trilha `platform.limits.set` de/para em par com `platform.change.requested`). Pela CLI do dono: `limits-set`.
- **Imposição** em `app/core/limits.py`, ao **criar**: OLT pela tela (`POST /v1/fleet/olts`) e OLT nova vinda do Edge (`/v1/edge/olt-snapshots`; OLT já conhecida continua reportando), Edge e membro pela CLI do dono (não há rota HTTP que crie Edge ou membro). `409 limit_reached` com `X-Limit-Resource/Max/Current`. O teste é "já tenho >= máximo", sob trava consultiva por (organização, recurso): criações simultâneas não passam do máximo. **Nunca** apaga nem bloqueia o que existe; reduzir abaixo do uso só impede novos.
- **Ingestão por organização**: um balde por organização (todos os agentes juntos) **além** do balde por agente; `429 organization_rate_limited` com `Retry-After`; o orçamento da organização é lido de `tenant_limits` com cache de 30 s (falha de leitura usa o padrão e registra). Mesma regra de versão: só se aplica a Edge que anuncia entender 429.
- Console: o detalhe mostra uso, limite efetivo, selo padrão/ajustado e o histórico; a organização **não** altera o próprio limite.
- Não é cobrança: sem plano, preço, medição histórica ou fatura (D0).

### D4 — E-mail transacional (fatia C, **Accepted e construída**; decisão de risco no ADR-0048, migração 0056)
SMTP do ambiente da plataforma (nunca por organização), TLS sempre; fila `email_queue` + worker `mailer`. Convite e troca de senha por e-mail são **ato explícito** do administrador (`send_email=true`; a tela continua mostrando o link); avisos sem segredo (segundo fator redefinido; organização suspensa/reativada, aos `isp_admin`) saem sozinhos. Link só de `PUBLIC_BASE_URL`, corpo apagado ao enviar, aplicação não lê o corpo, auditoria sem o link. Sem alerta por e-mail. Detalhes, riscos R-C1 a R-C3 e provas: `ADR-0048-email-transacional.md`.

### D5 — RBAC com escopo por site/OLT (fatia D; reabre o ADR-0031 item 3)
A decisão de 2026-10-30 ("DEPOIS") passa a ter posição na fila: **depois de A, B e C**. Papéis customizados continuam **NÃO** (ADR-0031 decisão 1). O desenho do item 3 (escopo como predicado de RLS, `app.scope`, inventário de rotas) vale sem mudança; esta ADR não o altera.

### D6 — Política de segurança por organização (fatia D/E, Proposed)
`tenant_security_policy` (MFA obrigatório por papel e duração de sessão) que **só pode apertar**, nunca afrouxar, o piso global (`FIBERCORE_MFA_REQUIRED_ROLES`, TTLs do ambiente). Falha fechada se a linha for ilegível.

### D7 — API com tokens por organização, webhooks e SSO (fatia F, Proposed; ADR próprio cada)
Fora desta decisão. **White-label: não planejado** (só se alguém pedir).

## Ordem e fatias
| Fatia | Conteúdo | Estado |
|---|---|---|
| **A** | D1 suspensão/reativação/renome com imposição + D2 console (saúde, flags, histórico) | **Accepted, construir agora** |
| B | D3 limites técnicos por organização | **Accepted, construída** |
| C | D4 e-mail transacional (ADR-0048) | **Accepted, construída** |
| D | D5 escopo por site/OLT; D6 política por organização (ADR-0049) | **Accepted, construída** (escopo v1 só leitura; sem duração de sessão) |
| E | Encerrar organização (exportar e apagar) | **Accepted, construída** (ADR-0050): operador pede, dono exporta e apaga |
| F | API com tokens, webhooks, SSO | F1 tokens e F2 webhooks **construídos** (ADR-0051); **F3 SSO proposto, não construído** (precisa de IdP real) |

## Alternativas descartadas
- **Impor a suspensão por política de RLS em todas as tabelas:** invasivo (dezenas de políticas) e deixa o login mudo; a checagem central em `get_principal` cobre usuário e Edge com um ponto só e mensagem clara. A RLS continua sendo a defesa de isolamento entre organizações; a suspensão é política de acesso.
- **Revogar tokens ao suspender:** exige varrer sessões e contas de serviço e não é reversível sem novo login; a checagem por requisição é imediata nos dois sentidos.
- **Dar `UPDATE` em `tenants` e `tenant_features` à role da aplicação:** uma falha da API permitiria alterar qualquer organização; as funções estreitas mantêm o contrato do ADR-0046 D1.
- **Ligar flags de escrita pela tela:** uma sessão de operador comprometida ligaria escrita em rede; essas ficam só com a CLI do dono.
- **Hierarquia/revenda e faturamento:** decisão do responsável (D0).

## Riscos declarados
- **R-A1 (herdado, ADR-0046 R-3):** o banco não prova que o operador iniciou a chamada; quem controla a API pode escolher `p_actor`. A auditoria em par e o MFA recente mitigam, não eliminam.
- **R-A2:** um operador (ou conta de operador comprometida) pode **suspender qualquer organização** (disponibilidade). Mitigação: MFA recente, motivo obrigatório, auditoria visível ao administrador da organização, reversão imediata, quebra-vidro pela CLI. Aceito por ser o papel do operador.
- **R-A3:** uma consulta a mais por requisição (`tenants.status`). Custo pequeno (chave primária); medir no p95 do e2e e na LAB.

## Consequências e provas exigidas (fatia A)
- Migração **0054** (4 funções `SECURITY DEFINER` novas e `platform_list_organizations` estendida com saúde, sem `UPDATE` direto em `tenants`/`tenant_features` para a role da aplicação). Reversível (`DROP FUNCTION`; nenhuma coluna nova de dados).
- Testes: suspensão bloqueia **usuário e Edge** (`403 organization_suspended`) e **não** afeta a outra organização (suíte de isolamento estendida); reativação restaura sem novo login; idempotência; motivo ausente `422`; não operador `403`; sem MFA recente `403`; role da aplicação sem `UPDATE`/`INSERT` em `tenants` e `tenant_features`; par de auditoria; renome duplicado `409`; flag desconhecida `422`; flag `OWNER_ONLY` `403` e pré-condição de `EDGE_SUPPORT` recusada; lista sem dado de cliente final (varredura de impressões digitais, como na suíte de isolamento).
- Web: lista com estado e saúde, detalhe com flags e histórico, diálogo de motivo; `axe` e e2e; how-to da Central de Ajuda; aviso claro ao usuário de organização suspensa.
- Rollback: reativar a organização (tela ou CLI); `alembic downgrade 0053` remove as funções; nada muda nos dados das organizações.
- Fora desta fatia: tudo de B a F e a encerração de organização.

## Registro de revisão (2026-11-13)
Codex r1 sobre a API (`raw/630-org-lifecycle-api-r1.txt`): 1 HIGH (lista de flags só na rota: corrigido, agora também no banco, com teste de chamada direta e de igualdade das listas), 2 MEDIUM (CLI `create-tenant` sem a trava e a regra de nome: corrigido; `org-status` sem `request_id` e sem evento: corrigido) e 1 LOW (`POST /v1/auth/service-token` ainda emite token a conta de organização suspensa; o token não passa de `get_principal`, então **aceito**: emitir não dá acesso).
