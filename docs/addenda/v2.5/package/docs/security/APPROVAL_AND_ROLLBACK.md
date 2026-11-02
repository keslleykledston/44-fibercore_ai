# Segurança de provisionamento e reversão

- Acesso: N1 `discovery.read`, `onu.authorize.request`; N2 `profile.preview`, `onu.authorize.approve` conforme política; Engineer `profile.publish`, `profile.deploy`; Auditor `audit.read`; Admin pode delegar, nunca burlar a homologação.
- Separação de funções (maker-checker) para deploy em múltiplas OLTs, mudanças de VLAN/uplink e alteração de perfil existente. OP aprovador não deve aprovar seu próprio batch crítico.
- Escrita OLT somente com `driver_certified`, firmware/placa homologada, snapshot fresco, target definido, janela adequada, device allowlist, guardrail de impacto, controle de rate/concorrência, e `plan_hash` aprovado com expiração.
- `AUTO_FIND_ENABLE` separado de `ONU_AUTHORIZE`. Não criar política que autoriza automaticamente tudo o que for descoberto.
- Serial, LOID, PLOAM password: secrets no vault; jamais salvar plaintext no banco/logs/UI/LLM ou screenshots.
- Limites Edge: outbound mTLS; no raw shell commands aceitos de cloud/browser; allowlist de IP/host e interface privada; credenciais por tenant e device, privilégio mínimo.
- PON do operador pode estar saturada, CTO ligada a outro contrato, OU ONU em outro cliente/OLT: bloquear com caso para revisão humana.
- Execução em etapas: identificar/lock → preflight → reusar/criar profiles → registrar ONU → service mapping → readback → verify. Persistir step status, não dizer `SUCCESS` apenas por ACK CLI.
- Reversão: somente componentes **novos e sem referências** e se seguro; nunca remover profile compartilhado ou apagar ONU existente de forma automática. Se parcial ou desconhecido: estado `NEEDS_REMEDIATION` com runbook. Se OLT ficar inacessível, não fazer retry cego.
- Batch por OLT: canário 1 alvo + verificação + aprovação expandida; abortar alvos posteriores em falha.
- Teste de auditoria multi-tenant, duplicate S/N, concurrent approval, stale snapshot, rollback, credentials redaction e replay protection.
