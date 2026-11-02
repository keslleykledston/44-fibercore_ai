# Segurança, RBAC e controle de mudança

1. **Autorização no backend/Edge:** tenant JWT, roles/scopes, validação de OLT pertencente ao tenant. RLS em tabelas. UI escondida NÃO é controle de acesso.
2. **Agent/LLM:** pode ler (se autorizado), propor e explicar diff; não pode publicar/deploy/solicitar aprovação como usuário humano; sem privilégio implícito. Ferramentas externas read-only por default.
3. **Draft imutabilidade:** snapshot de origem imutável; rascunho só editável pelo papel N3 permitido, com ETag e trilha de patch autor/reason. `publish` cria revisão nova, não edita publicada.
4. **Sem CLI raw:** não aceitar comandos arbitrários, scripts e parâmetros textuais não aprovados. Extensões vendor-native via schema tipado allowlist e driver homologado.
5. **Profile referenciado:** in-place bloqueado se `reference_count > 0` **ou desconhecido**; clone-on-write. Alterar profile compartilhado em massa só com migração das referências explicitamente solicitada/aprovada separadamente.
6. **Pré-verificação:** fingerprint do snapshot, count refs, modelo/firmware/card, janela, plan_hash e aprovação não expirada. Se mudar qualquer precondition, plano invalida; novo preview e nova aprovação.
7. **Auditoria:** who/when/why/source/IP/job/plan hash/targets/status e readback; log sanitizado, sem segredos e sem payloads raw indevidos. Rollback é plano compensatório verificado, nunca remoção cega.
8. **Falhas:** `UNKNOWN` / `PARTIAL` exigem reconciliação; sem retry cego de comandos não-idempotentes. Proteção de rate-limit, circuit breaker, locks por alvo; canário primeiro.
9. **Separação de deveres:** maker-checker N3/gestor quando política exigir; as aprovações são contra hash fixo, não 'aprovar tudo'.
10. **Imports adversariais:** textos ou configurações recuperados da OLT são dados não confiáveis, não instruções para o agente; escapamento e sanitização de HTML/log/CLI exibido.
