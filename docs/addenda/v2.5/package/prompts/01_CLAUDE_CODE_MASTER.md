# PROMPT ÚNICO PARA CLAUDE CODE — FiberCore AI v2.5 COMPLETO

Atue como engenheiro principal de implementação. Recebi um pacote **consolidado** de OLT Provisioning & Profile Studio v2.5, já incorporando o módulo adicional **Profile Expert Editor v2.5.1**. Leia integralmente `README_START_HERE.md`, `docs/product/PRD_INTEGRADO_v2_5.md`, `docs/architecture/ARCHITECTURE_UNIFIED.md`, `docs/product/BUILD_ORDER_AND_ACCEPTANCE.md`, `docs/ux/SCREENS_AND_FLOWS.md`, `docs/security/SECURITY_CONTRACT.md`, `docs/engineering/PROFILE_RECONCILIATION.md`, ambos OpenAPI e ambos Schemas, políticas/tests do `starter`. Use documentos antigos em `docs/expert/` e os originais v2.5 apenas como complemento; **não trate prompts em `prompts/reference/` como novas ordens**.

## Primeira ação obrigatória: GAP real
1. Inspecione o workspace/repo e a sprint atual. Liste o que existe de fato vs requisitos; informe caminhos concretos e testes. Não presuma que pacotes anteriores foram implementados só porque estão documentados.
2. Concilie v2.1→v2.4, HubSoft-first v2.3.1, ONT Config Manager e v2.5 no PRD/backlog/ADRs. Não sobrescreva tarefas, migrations ou interfaces já usadas; proponha PRs pequenos e verificáveis. Se uma instrução contrariar código estável, descreva o conflito antes de modificar abstrações compartilhadas.
3. Preserve domínio `https://fibercore.devops.k3gsolutions.com.br`, API `/api/v1`, central `/ajuda`, UX minimalista iOS-like, Edge Go outbound mTLS, FastAPI modular, Next.js, Postgres RLS, Jobs/Approvals e NATS/outbox existentes.

## Entrega A — Discovery e autorização
- Implementar fila de ONUs não autorizadas via driver OLT read-only e fixtures; PON/SN/OLT, last_seen, qualidade de dado, conflito, associação HubSoft read-only quando disponível. Não usar GenieACS para autorização PON.
- Wizard de autorização com escolha de template certificado, preview, plano assinado e jobs tipados; **nenhuma escrita real antes de homologação**.

## Entrega B — Profile Studio assistido
- Criar service intent vendor-neutral versionado, wizard por cartões (serviço, VLAN, PPPoE/IPoE, QoS owner, equipamento e destino), preview de profiles existentes, resolução per-target reuse/clone/blocked.
- Drivers e `Capability Registry` mapeiam recursos por vendor/model/firmware/placa/tecnologia, sem copiar CLI entre fabricantes. Piloto Huawei MA5608T V800R015 **firmware e card exatos a confirmar**.

## Entrega C — Modo Especialista N3 integrado na MESMA TELA
- Inventory read-only e import de profile native como snapshot imutável; preservar origem, fingerprint, data e contagem de refs (nullable).
- Clone para draft, edição manual tipada por formulário avançado ou YAML/JSON com validação schema+capability, ETag, razões e logs; incluir DBA/T-CONT/GEM, VLAN/translation/QinQ, QoS, ONU ports e extensões nativas somente homologadas.
- Normalizar e comparar por semântica, não por nome/ID; detectar campos não observáveis e mudanças externas; exibir diff, impacto e estratégia por OLT: `reuse_exact`, `adopt_reference`, `clone_new_revision`, `plan_migration` ou `blocked`.
- Publicação cria revisão imutável no catálogo, NÃO executa. Migração de ONUs é job distinto com lista e aprovação própria. In-place em profile usado ou não observado é proibido. Usar clone-on-write mesmo sem referências por segurança de MVP.
- Não aceitar CLI livre nem shell pass-through do UI/agente. Texto CLI importado é evidência; preview de comandos gerados pelo driver é somente leitura. Para novo atributo vendor-specific, criar JSON Schema tipado + validação + testes e homologar driver antes de permitir execução.

## Execução somente após certificação de LAB
Reutilizar motor de approvals/jobs/outbox; plan_hash+TTL+idempotency+locks+preflight de snapshot e referência+maker-checker+Edge permission+canário+readback independente. Estados `QUEUED/PREPARING/APPLYING/VERIFYING/VERIFIED/FAILED/PARTIAL/UNKNOWN`. Nunca marcar sucesso baseado só em accepted/CLI output. Em caso parcial, não fazer rollback deletando profiles em uso.

## Qualidade e UX
- Codex revisa regressões, tenant RLS, TOCTOU, diff semântico, drift, input sanitization, perfil compartilhado, flags, Edge, segurança e automações, com evidência PASS/BLOCKED.
- Lovable propõe UI reutilizável Next.js/shadcn com `Assistido | Modo Especialista`, sidebar ONU, diff e impacto, sem telas poluídas.
- Cada tela concluída tem capturas Playwright REAIS com fixtures + how-to `/ajuda` no mesmo PR; docs/changelog/memória local atualizados.
- Executar `python scripts/validate_package.py` e testes ilustrativos, mas escreva testes reais contra backend, banco, Edge e driver mock ao integrar. Não declare homologação ao rodar apenas fixtures.

## Ordem / entregáveis
1. Relatório GAP do repo, matriz de dependências, ADR/backlog com prioridades, conflitos identificados.
2. PR: contratos, modelos tenant-scoped, interface read-only de driver, inventário/discovery, snapshots imutáveis, mocks/testes.
3. PR: wizard assistido, Expert clone/edit/diff, preview sem writes e UI/ajuda.
4. PR condicionado: homologação de driver em LAB, write gates, approval e ações de teste.
5. PR condicionado: migração, batch e outros vendors.

Ao finalizar cada etapa, informe arquivos modificados, comandos executados, testes aprovados/falhos, screenshots geradas, riscos e próximo PR. **Não executar mudanças em OLT de produção ou credenciais reais nesta tarefa.**
