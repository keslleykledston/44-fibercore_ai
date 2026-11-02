# Homologação e critérios de aceite

## Etapa A — com fixtures, sem OLT
- Import imutável de snapshot OLT; não modifica OLT, status e timestamps corretos.
- Mesmo nome + hash diferente -> conflito, nunca overwrite.
- Profile compartilhado / ref count unknown -> bloquear in-place; variante permitida como draft.
- Reuse por equivalência semântica comprovada, não pelo nome.
- Diferenças DBA fixed/assured/max, T-CONT/GEM e VLAN tagging preservadas.
- RBAC: N1 não edita; N3 edita draft; cross-tenant = negado independentemente da UI.
- ETag stale impede overwrites concorrentes; arquivo de import não contém credenciais.
- Não há endpoint de CLI raw; usuário pode visualizar apenas CLI redigida read-only se driver suporta.
- Toda comparação mostra proveniência e `not_observable` para campos não lidos.
- Playwright desktop/mobile + documentação How-to com captura no PR.

## Etapa B — laboratório Huawei MA5608T R015 (apenas quando confirmado)
- Identificar patch, placa GPON, versão firmware, capabilities/feature flags e modelo ONU.
- Capturar snapshot e contagem real de referências, validar parser contra a saída real sem segredos.
- Clone de profile que não altera original, verificar nova versão e bindings por readback independente.
- Confirmar que ONU no profile antigo continua funcionando; migração canário em cenário controlado, aprovada separadamente.
- Simular falha após etapa intermediária; resultado `PARTIAL/UNKNOWN` e runbook explícito, sem delete cego.
- Registrar logs sanitizados, duração, hashes e aprovação por alvo. Proibir produção até aprovação de release.

## Fase C — pilotos por OLT / vendor
- Cada novo fabricante/firmware/placa precisa de seu próprio conjunto de fixtures, testes de leitura, lab de escrita e checks de QoS/serviço.
- Regressão v2.5 descoberta, HubSoft-first e v2.4 ONT Config obrigatória.

**Evidência:** testes do demonstrativo não substituem certificação real do driver, OLT ou mudança de infraestrutura.
