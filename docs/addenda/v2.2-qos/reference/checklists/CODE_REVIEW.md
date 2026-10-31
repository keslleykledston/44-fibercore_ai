# Gate de revisão — Codex

## Preservação
- [ ] Diff não replica backend TR-143, adapter ACS, jobs, banco de speed, drawer ou Central de Ajuda.
- [ ] `CURRENT_STATE`, `GAP_MAP` e arquitetura referenciam arquivos reais.
- [ ] Nenhuma nova exposição NBI/Mongo, outro ACS, broker, USP ou microserviço desnecessário.

## Corretude
- [ ] TR-181/IGD detectados sem path/índice fixo; capabilities por firmware, writable e WAN de serviço verificada.
- [ ] Resultado ativo não reutiliza `Complete` antigo; HTTP 200/202 não conta como conclusão do diagnóstico.
- [ ] Estados `stale`, `not_available`, `not_supported`, `not_applicable`, `inconclusive` são distintos; sem 0 falso.
- [ ] Óptica dBm×1000 só no campo TR-181 oficial; delta de contadores reconhece reset.
- [ ] Não chama PHY Wi-Fi de throughput; sem jitter obtido por diferença min/max ping.
- [ ] `COMPLETO` faz referência ao SD-001 e respeita seus locks/limites.

## Segurança, UX e QA
- [ ] RBAC, tenant/IDOR, allowlist, idempotência, auditoria, payload/log sanitizado e feature flags.
- [ ] Tests em mock para CWMP 202/stale/bridge/firmware/permissões/concorrência.
- [ ] O drawer preserva fluxo atual e mostra origem, horário, falha parcial e explicações.
- [ ] Screenshots de UI real e how-to atualizados; nenhuma evidência fictícia alegada como produção.
- [ ] Plano de rollback com flag QoS não desabilita SD-001.
