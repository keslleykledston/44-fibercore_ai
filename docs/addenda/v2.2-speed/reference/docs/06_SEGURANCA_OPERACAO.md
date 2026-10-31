# Segurança, operação e proteção da rede

## Regras obrigatórias
1. **Autorização**: permissão explícita `diagnostics.speed.run` (ou permissão existente equivalente). Viewer: somente leitura. Todas requisições verificadas contra tenant no backend.
2. **Edge outbound**: GenieACS NBI 7557 e Mongo somente redes internas; host FiberCore não acessa o NBI diretamente pela Internet.
3. **URLs de teste fixas/allowlist**: evitar SSRF; operador não digita IP/URL/porta do destino. Catalogar `CORE` e `INTERNET` via configuração segura. Não permitir redirecionamentos para destinos arbitrários.
4. **Upload sintético**: PUT com bytes gerados pelo CPE, descartados pelo servidor. Nunca arquivos reais do assinante.
5. **Sem segredo na URL**: preferir ACL de IP de origem, firewall e endpoint dedicado. Se houver token efêmero, impedir vazamento em logs/telemetria; não depender de cabeçalhos que ONT não suporta.
6. **Limites padrão**: 1 teste ativo por ONT; 1 por PON; 2 simultâneos por tenant; prazo configurável com teto; sem disparos automáticos; respeitar janelas críticas do NOC.
7. **Feature flag**: disable de jobs novos sem afetar inventário, provisionamento ou telemetria.
8. **Auditoria**: usuário, tenant, ONT, perfil/modelo, interface, destino lógico, ação, tempos e resultado. Jamais senha TR-069/ACS ou dados de assinante no log.
9. **Endpoint saudável**: health check, CPU/rede, latência básica e medição de capacidade do nó antes de homologar; o servidor não deve ser o gargalo.
10. **RBAC + aprovação**: acionar teste de carga com confirmação/aviso; manter política do FiberCore para escrita em dispositivos. Não criar exceção silenciosa porque teste é diagnóstico.

## Falhas e degradação
- Edge fora: módulo informa indisponibilidade, sem travar ONU 360.
- ACS HTTP 202: manter `Aguardando conexão` e não declarar sucesso.
- CPE sem Inform de retorno: consulta controlada; no timeout `inconclusivo`, não repetir Requested em loop.
- Upload falha, download válido: `partial`, preservar valor válido.
- Servidor sobrecarregado: `failed/inconclusive` com aviso e métrica do nó, evitar atribuir culpa ao CPE.
- Cancelamento: só garantir remoção de job **antes** do envio; depois do `Requested`, parar acompanhamento não garante interromper o tráfego no CPE. Não prometer `Parar teste` sem capacidade real homologada.

## Parâmetros de operação iniciais para homologação
- Download e upload sequenciais; arquivos iniciais em 16/64/128/256/512 MiB, escolhidos por perfil e limite de firmware.
- Não exceder `maxFileSize` homologado do modelo; tentativa curta pode não medir pico (marcar resultado parcial).
- `directionTimeoutSec`: 120 por direção (configurável e com teto); `pollEverySec`: 3–5 enquanto necessário, evitando refresh agressivo do ACS.
- Retenção de histórico por política existente; manter agregados úteis sem registrar toda carga de dados.

## Observabilidade e rollback
- Logs estruturados por `runId`, Edge `taskId`, `tenantId` e device id mascarável.
- Métricas: jobs running/queued; conclusão válida/parcial/timeout, latência de ACS, fila, uso de bytes por PON/nó e faults por fabricante/firmware.
- Alertar se falhas/timeout aumentarem em homologação. Rollback: desligar feature flag e reverter somente migração/código novo conforme política de releases; nenhuma perda de funções de monitoramento.
