# Contrato de segurança — v2.5 completo

1. **Default no-write:** `discovery=true`, `profile_import=true`, `dry_run=true`, `olt_writes=false`, `bulk=false`, `migration=false`. Nunca habilitar flag de escrita no deploy por padrão.
2. **RBAC e tenant no backend + Edge:** N1 pode visualizar/preparar, N2 conforme política aprovar, N3 alterar drafts; aprovação executada por pessoa distinta quando exigido. Sem bypass UI, API, LLM ou serviço.
3. **LLM só propõe:** acesso a observações permitido com RBAC; sem executar diretamente, publicar/aprovar ou modificar template publicado. Qualquer recomendação é não confiável até validada.
4. **Identidade do alvo:** tenant, OLT ID, chassis/slot/PON, serial, modelo/firmware/placa e capability/permissão. Revalidar antes do write (TOCTOU).
5. **Plano criptograficamente ligado ao contexto:** `plan_hash` de intent revision+target+diff+preconditions+TTL+approvals; mudança após preview invalida aprovação.
6. **Profile em uso/unknown:** sem edição in-place; clone-on-write. Migração só em job separado com lista de ONUs, análise de impacto e aprovações específicas.
7. **Comandos controlados:** editor só gera payload declarativo; driver allowlisted fabrica ações tipadas a partir de schema certificado; nenhum shell/CLI passthrough, sem credenciais em configs exportadas.
8. **Atomicidade limitada:** OLTs podem falhar após parcial; não fazer blind retries; usar idempotência/readback, registrar PARTIAL/UNKNOWN e plano de compensação seguro.
9. **Concurrency:** locks por OLT/profile/ONU e limites de taxa. Outbox NATS e jobs existentes para não perder intenções, sem dupla execução.
10. **Audit e privacy:** who/why/when/hash/target/state, sempre redigindo LOIDs/credenciais; fixtures sintéticas e screenshots sem cliente real.
11. **Deploy:** homologação LAB por vendor/model/firmware/patch/card/operation, canário, manutenção quando necessário, rollback como novo plano autorizado.
12. **Imports**: configurações obtidas são dados não confiáveis; sanitizar HTML/ANSI/controle, parser não executa texto ou interpreta instruções do equipamento como prompt de IA.
