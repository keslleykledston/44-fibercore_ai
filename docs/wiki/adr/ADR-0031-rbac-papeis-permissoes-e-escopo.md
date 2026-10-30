# ADR-0031: RBAC — catálogo de permissões, papéis por provedor, escopo e governança de mudança

Status: Proposed (revisado após a rodada 1 do Codex; aguarda aprovação do responsável antes da construção do que depende das perguntas) | Data: 2026-10-30 | Owner: equipe | Origem: pedido do responsável em 2026-10-30 ("desenho e construção do RBAC").

## Contexto

**O que existe hoje (verificado no código):**
- 8 papéis FIXOS em `ROLE_PERMISSIONS` (`apps/api/app/core/security.py`): `isp_admin`, `engineer`, `noc_n2`, `noc_n1`, `support`, `auditor`, `platform_support`, `edge_agent`. Cada membro tem UM papel (`tenant_memberships.role`).
- 18 permissões em uso, checadas por rota com `require("…")`: `inventory:read|write`, `incidents:read|ack`, `associations:review`, `customers:read|import`, `jobs:read|request|approve|execute`, `diagnostics:run`, `members:read|mfa_reset`, `tenant:read`, `edge:read|heartbeat`, `audit:read`.
- Isolamento entre provedores por RLS forçada; `tenant_id` nunca vem só de header. MFA obrigatório por papel (`MFA_REQUIRED_ROLES`, falha fechada no boot). Separação de funções em jobs (quem solicita ≠ quem aprova, exceto a bancada do ADR-0030). Auditoria de ações em `audit_log`.

**Lacunas:** (1) o catálogo não é fonte única: a tabela de papéis de `docs/security/SECURITY_AND_APPROVALS.md` (Wi-Fi/PSK, CSV, releases) não corresponde ao código; (2) não há papéis por provedor (um ISP pequeno e um NOC gerenciado têm necessidades diferentes); (3) não há escopo menor que o provedor (um técnico de uma cidade vê as OLTs de todas); (4) não há tela nem API para atribuir/alterar papéis, nem travas (último admin, auto-escalada); (5) nenhum teste prova a matriz inteira nem que toda rota tem permissão declarada; (6) a delegação da `platform_support` está só nomeada.

**Restrições:** não mudar o que cada papel atual pode fazer hoje; nada de produção sem gate formal (estados permitidos: LAB/INTERNAL_PILOT…); permissão nunca é a única defesa de uma escrita em equipamento (continuam o gate `HOMOLOGATED_WRITES`, a homologação por perfil e a aprovação do job); segredos fora do repositório.

## Opções

A. **Manter papéis fixos no código**, só documentar e testar. Barato, seguro, mas não atende provedores diferentes nem escopo.
B. **Papéis 100% livres por provedor** (qualquer combinação de permissões). Flexível, porém permite montar combinações perigosas (ex.: solicitar e aprovar, ler PII e exportar) e dificulta suporte e auditoria.
C. **Papéis de sistema imutáveis (modelos) + papéis customizados por provedor limitados por um teto, com escopo opcional e travas de governança.** Recomendada.

## Decisão (proposta — opção C)

### 1. Catálogo único de permissões
Fonte única no código (`app/core/permissions.py`): cada permissão tem `nome` (`recurso:verbo`), descrição, **risco** (R0 leitura, R1 leitura sensível/PII, R2 ação reversível, R3 ação irreversível ou de segurança), se **exige MFA recente**, e se **admite escopo**. A matriz papel × permissão em `docs/` é GERADA do catálogo (nunca editada à mão). Novas permissões previstas: `devices:read` (CPE/Edge/capacidades; hoje cobertas por `inventory:read`/`edge:read`), `devices:act:<operação>` (por operação homologada, nasce desligada), `roles:read`, `roles:manage`, `members:manage`, `audit:export`, `reports:export` (CSV de ONUs offline), `customers:export`.

### 2. Papéis
- **Papéis de sistema** (os 8 atuais): imutáveis, versionados, com exatamente as permissões de hoje. Servem de modelo e de fallback.
- **Papéis customizados por provedor** (`tenant_roles`, `tenant_role_permissions`, RLS): copiam um papel de sistema e só podem **remover** ou **adicionar** permissões dentro do **teto** do provedor (abaixo). `edge_agent` e `platform_support` não são customizáveis.
- **Teto (invariantes que nenhum papel customizado quebra):** nenhuma permissão R3 sem `isp_admin` aprovando; **papel customizado nunca contém `jobs:request` e `jobs:approve` ao mesmo tempo** (só o papel de sistema `isp_admin` mantém a combinação, como hoje); PII (`customers:read`, `customers:export`) nunca vem sem auditoria de acesso; `roles:manage`/`members:manage` só `isp_admin`.
- **Separação de funções é regra do motor de jobs, por operação e por ator, e não depende da composição do papel:** quem solicitou um job não o aprova, para qualquer papel e qualquer operação; **a única exceção é a das operações de bancada do ADR-0030** (autorização prévia de uso único do responsável, 1 aprovação que pode vir do solicitante) e nenhum papel customizado, delegação ou escopo a amplia. Teste: papel customizado clonado de `isp_admin` não consegue autoaprovar fora da bancada nem criar a combinação.
- Um membro tem **um papel por provedor**; acumular papéis fica de fora (somar papéis esconde a combinação perigosa).

### 3. Escopo
Escopo opcional por atribuição: `provedor` (padrão) → `site` → `OLT` → `PON`. **O escopo é um predicado obrigatório no acesso aos dados, não um filtro de tela:** aplicado no banco (políticas de RLS em `olts`, `pon_ports`, `onus`, incidentes e derivados, lendo `app.scope` definido junto de `app.tenant_id` na mesma conexão), de modo que listas, **totais e contagens** (`onu_count`, `excluded.stale`, `excluded.unknown_start`, KPIs do NOC), **relatórios e CSV** e subconsultas herdam o recorte sem código por endpoint. Filtros de entrada (`olt_id`, `pon_path`) fora do escopo se comportam como se o identificador não existisse (**404/lista vazia, nunca 403**, e nenhum cabeçalho ou contagem diferente do que um provedor sem essa OLT mostraria).
- **Recursos sem vínculo com OLT (clientes, CPEs sem ONU vinculada, membros, auditoria) não são escopáveis:** um papel com escopo restrito simplesmente não recebe as permissões desses recursos (`customers:*`, `members:*`, `audit:*`, CPEs); isso evita vazar existência por agregação.
- **Inventário obrigatório de endpoints:** a entrega de escopo só fecha com um teste que percorre TODA rota autenticada com permissão de leitura de inventário e prova, com um principal restrito, que corpo, contagens, cabeçalhos e CSV não revelam nada fora do escopo.
- Permissões sem sentido por escopo (`members:*`, `roles:*`, `audit:*`) são só de provedor. Fase posterior ao núcleo (entrega 4).

### 4. Governança de mudança de papel
- Só quem tem `members:manage` atribui; **ninguém atribui papel com mais permissões do que o próprio** nem altera o próprio papel; **não se remove nem rebaixa o último `isp_admin`**; conceder papel com R3 exige **MFA recente** do concedente e MFA ativo do beneficiário.
- Toda concessão/remoção/edição de papel grava `audit_log` (quem, quem recebeu, antes/depois, motivo) e emite evento; sessões do beneficiário são revogadas na mudança.
- **Concorrência:** toda mudança de papel/membro passa por UMA função que, na transação, primeiro trava a linha do provedor (`SELECT … FROM tenants WHERE id = :t FOR UPDATE`, trava comum por provedor), depois as linhas de membership alvo em ordem de id, e só então conta os `isp_admin` ativos e aplica as travas e o teto. Duas mudanças simultâneas se serializam na trava do provedor: dois admins removendo um ao outro nunca zeram o provedor. Teste com duas transações concorrentes.

### 5. Delegação da plataforma e contas de serviço
- `platform_support`: só por **delegação com prazo e motivo** (`membership_delegations`), visível ao `isp_admin` e auditada; sem acesso a PII por padrão. **A resolução do principal (`get_principal`) exige uma delegação ativa e não expirada em CADA requisição** (consulta no banco, nunca só o que o token diz); sem delegação válida o membership `platform_support` não resolve (401/403). Memberships `platform_support` que já existam sem delegação são **invalidadas pela migração** (desativadas) e só voltam por uma delegação nova; a expiração vale no instante (`now() < expires_at`), sem depender de fim de sessão.
- Edge/contas de serviço: permissões mínimas por função (`edge_agent` não muda); token ligado a um Edge; revogação imediata.

### 6. MFA por risco
`MFA_REQUIRED_ROLES` continua; soma-se **MFA recente** (janela curta) para permissões marcadas no catálogo (R3, conceder papel, exportar PII).

### 7. Leitura de papéis, compatibilidade e migração (sem mudar comportamento)
- **Modelo de leitura:** `Principal.can()` passa a usar `resolve_permissions(membership)`: papel de sistema → `ROLE_PERMISSIONS` do código (inalterado); papel customizado → conjunto da tabela, calculado dentro do teto. `tenant_memberships.role` continua guardando a chave do papel de sistema; o customizado entra por `role_id` (nulo para os atuais).
- **Compatibilidade de schema:** o CHECK de `tenant_memberships.role` (migração 0001, hoje sem `edge_agent`) é substituído por restrição que cobre os 8 papéis de sistema; contas de serviço continuam em `service_accounts`. `required_mfa_roles()` passa a avaliar o **papel de sistema base** de cada customizado (ou a marca de MFA do catálogo, a que for mais estrita) e continua falhando fechado em nome desconhecido.
- **Rollback fail-closed:** com a flag do provedor desligada (ou tabelas ilegíveis), membros de papel customizado resolvem para **nenhuma permissão além de `tenant:read`** até serem reatribuídos a um papel de sistema; nunca para o papel base, que pode ter mais poder que o customizado.
- **Ordem:** 1) catálogo + teste de inventário (sem alterar nada em produção); 2) tabelas e CHECK, papéis de sistema como sementes; 3) API e tela; 4) escopo; 5) delegação e MFA recente. Cada etapa reversível; nenhuma exige mudar o papel de quem já existe.

## Perguntas ao responsável (precisam de resposta antes da construção)
1. Papéis customizados por provedor entram já no MVP, ou ficamos só com os 8 papéis + catálogo + tela de leitura e atribuição (opção A+)?
2. Escopo por OLT/site é necessário agora (NOC gerenciado com vários clientes de campo)? Se não, fica para depois da tela.
3. Quem pode conceder papéis de risco: só `isp_admin`, ou também um papel "gestor de acessos" sem poder operacional?
4. Janela de "MFA recente" aceitável (sugestão: 10 minutos)?
5. Visão de `platform_support`: prazo máximo da delegação (sugestão: 8 h, renovável com novo motivo)?

## Consequências

- **Como testar:** teste de inventário de rotas e de matriz (positivo/negativo) por papel; tentativas de escalada (auto-atribuição, papel acima do próprio, último admin, concorrência de dois admins); isolamento entre provedores; escopo (fora do escopo = 404); revogação de sessão; auditoria completa; geração da matriz em `docs/` sem diferença (teste falha se divergir).
- **Rollback:** cada etapa é aditiva; desligar a flag do provedor devolve o comportamento dos papéis de sistema e, para quem tinha papel customizado, o fail-closed descrito na seção 7.
- **Monitorar:** mudanças de papel por dia, tentativas negadas de escalada, delegações ativas, membros sem MFA em papel que exige.
- **Revisão:** Codex adversarial em cada entrega (CRITICAL/HIGH bloqueiam); nenhuma exposição fora de LAB/INTERNAL_PILOT sem o gate formal.
- **Entregas:** (1) catálogo + teste de inventário + matriz gerada; (2) papéis no banco + API de atribuição com travas + auditoria; (3) tela Administração → Papéis e permissões; (4) escopo por OLT/site; (5) delegação da plataforma e MFA recente por risco. A entrega 4 da fase Dispositivos (ações na tela do CPE) usa as permissões `devices:act:*` da entrega 1.

## Registro da revisão adversarial (Codex)
- Rodada 1 (2026-10-30, `docs/wiki/reviews/raw/114-*`): 2 HIGH e 3 MEDIUM, todos incorporados acima — SoD por operação/ator com a exceção da bancada preservada (seção 2), escopo como predicado de dados cobrindo agregados, contagens e CSV com inventário obrigatório (seção 3), leitura de papéis/CHECK/MFA/rollback fail-closed (seção 7), trava comum por provedor para o último admin (seção 4), delegação exigida em cada resolução de principal e invalidação das memberships legadas (seção 5).
