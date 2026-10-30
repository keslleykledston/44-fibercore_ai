# ADR-0031: RBAC — catálogo de permissões, papéis por provedor, escopo e governança de mudança

Status: Proposed (aguarda aprovação do responsável antes de qualquer construção; depois Codex gate) | Data: 2026-10-30 | Owner: equipe | Origem: pedido do responsável em 2026-10-30 ("desenho e construção do RBAC").

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
- **Teto (invariantes que nenhum papel customizado quebra):** nenhuma permissão R3 sem `isp_admin` aprovando; um papel nunca combina `jobs:request` e `jobs:approve` a menos que seja `isp_admin` (separação de funções); PII (`customers:read`, `customers:export`) nunca vem sem auditoria de acesso; `roles:manage`/`members:manage` só `isp_admin`.
- Um membro tem **um papel por provedor**; acumular papéis fica de fora (somar papéis esconde a combinação perigosa).

### 3. Escopo
Escopo opcional por atribuição: `provedor` (padrão) → `site` → `OLT` → `PON`. Leituras e ações filtram por linha (`olt_id`/`pon`) e **negam por padrão fora do escopo** (um 404, nunca um 403 que revele existência). Permissões sem sentido por escopo (ex.: `members:*`) são só de provedor. Fase posterior ao núcleo (entrega 4 abaixo).

### 4. Governança de mudança de papel
- Só quem tem `members:manage` atribui; **ninguém atribui papel com mais permissões do que o próprio** nem altera o próprio papel; **não se remove nem rebaixa o último `isp_admin`**; conceder papel com R3 exige **MFA recente** do concedente e MFA ativo do beneficiário.
- Toda concessão/remoção/edição de papel grava `audit_log` (quem, quem recebeu, antes/depois, motivo) e emite evento; sessões do beneficiário são revogadas na mudança.
- Concorrência: a regra do último admin e do teto é verificada na mesma transação com trava de linha (dois admins removendo um ao outro ao mesmo tempo não zeram o provedor).

### 5. Delegação da plataforma e contas de serviço
- `platform_support`: só por **delegação com prazo e motivo** (`membership_delegations`), expira sozinha, visível ao `isp_admin` e auditada; sem acesso a PII por padrão.
- Edge/contas de serviço: permissões mínimas por função (`edge_agent` não muda); token ligado a um Edge; revogação imediata.

### 6. MFA por risco
`MFA_REQUIRED_ROLES` continua; soma-se **MFA recente** (janela curta) para permissões marcadas no catálogo (R3, conceder papel, exportar PII).

### 7. Migração (sem mudar comportamento)
1) Catálogo + teste de inventário (todo `require()` no catálogo; cada papel de sistema com exatamente o conjunto de hoje: matriz positiva e negativa) — sem alterar nada em produção. 2) Tabelas de papéis customizados, vazias; papéis de sistema como linhas semente. 3) API e tela. 4) Escopo. Cada etapa reversível; nenhuma exige mudar o papel de quem já existe.

## Perguntas ao responsável (precisam de resposta antes da construção)
1. Papéis customizados por provedor entram já no MVP, ou ficamos só com os 8 papéis + catálogo + tela de leitura e atribuição (opção A+)?
2. Escopo por OLT/site é necessário agora (NOC gerenciado com vários clientes de campo)? Se não, fica para depois da tela.
3. Quem pode conceder papéis de risco: só `isp_admin`, ou também um papel "gestor de acessos" sem poder operacional?
4. Janela de "MFA recente" aceitável (sugestão: 10 minutos)?
5. Visão de `platform_support`: prazo máximo da delegação (sugestão: 8 h, renovável com novo motivo)?

## Consequências

- **Como testar:** teste de inventário de rotas e de matriz (positivo/negativo) por papel; tentativas de escalada (auto-atribuição, papel acima do próprio, último admin, concorrência de dois admins); isolamento entre provedores; escopo (fora do escopo = 404); revogação de sessão; auditoria completa; geração da matriz em `docs/` sem diferença (teste falha se divergir).
- **Rollback:** cada etapa é aditiva (tabelas novas, rotas novas); desligar por flag de provedor devolve o comportamento atual (papéis de sistema).
- **Monitorar:** mudanças de papel por dia, tentativas negadas de escalada, delegações ativas, membros sem MFA em papel que exige.
- **Revisão:** Codex adversarial em cada entrega (CRITICAL/HIGH bloqueiam); nenhuma exposição fora de LAB/INTERNAL_PILOT sem o gate formal.
- **Entregas:** (1) catálogo + teste de inventário + matriz gerada; (2) papéis no banco + API de atribuição com travas + auditoria; (3) tela Administração → Papéis e permissões; (4) escopo por OLT/site; (5) delegação da plataforma e MFA recente por risco. A entrega 4 da fase Dispositivos (ações na tela do CPE) usa as permissões `devices:act:*` da entrega 1.
