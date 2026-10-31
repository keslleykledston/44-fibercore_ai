# Arquitetura mínima e fluxo

## Preservar o desenho existente
```
Operador (web same-origin /api/v1)
   │
   ▼
FiberCore API + Auth + RBAC + Auditoria + Feature flag
   │
   ├─ Capability Registry / Inventário / ONU 360 / Jobs existentes
   │
   ▼
Orquestrador de diagnóstico EXISTENTE (adicionar provider TR143)
   │
   ▼
Edge Connector outbound (host/tenant do cliente)
   │
   ▼
GenieACS NBI local → sessões CWMP → ONT (WAN de serviço confirmada)
                                      │
                                      ├─ HTTP GET  → Test Node Core
                                      └─ HTTP PUT  → Test Node Core
                                        ou nó externo aprovado (Internet)

Resultados: ONT → GenieACS → Edge Connector → FiberCore DB → sidebar.
```

- NBI do GenieACS: **somente rede interna**, nunca publicado; manter host GenieACS existente e Mongo separados do PostgreSQL do FiberCore.
- TR-369/USP permanece no controller específico, não altera este P0. Se houver adapter já pronto para diagnóstico via USP, conectar à mesma interface de domínio posteriormente.
- Sem novo microserviço FiberCore; adicionar **provider/módulo** ao engine de diagnósticos. O `Test Node` é um endpoint de tráfego externo à plataforma, opcional quando já houver servidor homologado.

## Fluxo detalhado por direção
1. A API confirma sessão/tenant/permissão, método suportado, firmware, WAN correta e endpoint aprovado disponível.
2. Cria `job` com chave idempotente e reserva slot de concorrência (dispositivo, PON e tenant); preserva plano nominal apenas se validado.
3. Seleciona tamanho de arquivo por perfil homologado (não gerar carga ilimitada); proíbe URL arbitrária.
4. Enfileira `setParameterValues` com `Interface`, `DownloadURL` **ou** `UploadURL`+`TestFileLength`, e `DiagnosticsState=Requested` na mesma tarefa; estado `despachado` ≠ `teste concluído`.
5. Para status HTTP GenieACS `200`, tarefa executada na sessão; `202`, pendente: observar tarefa/Inform e janela de timeout. Não disparar repetidamente `Requested` na tentativa de acompanhar.
6. Espera `8 DIAGNOSTICS COMPLETE` quando integração disponibiliza evento, ou consulta controlada **após** a tarefa. `getParameterValues`/`refreshObject` e leitura do CPE retornado pelo NBI.
7. **Verifica frescor/correlação**: timestamps dos parâmetros, intervalo de execução, eventual token de endpoint se suportado, tarefa e evidência de conclusão; rejeitar `Completed` antigo.
8. Valida `DiagnosticsState=Completed` e métrica temporal/bytes. Se erro, registrar `falhou` sem throughput fictício. Persistir resultado e avançar upload somente após download finalizado/timeout.
9. Finaliza `completed`, `partial`, `failed` ou `timeout`; libera todos slots; gera trilha de auditoria e evento para atualizações do frontend.

## Máquina simples de estados
`queued → dispatched → running/collecting → completed | partial | failed | timeout | unsupported`

Não duplicar filas existentes. Se não houver evento em tempo real, polling do FiberCore a cada 2–5 s enquanto drawer aberto, com hard timeout configurável (padrão 120 s por direção; ajustar ao perfil de homologação). Retries somente para consulta/leitura, não reemitir `Requested` automaticamente.

## Test node
- O serviço externo aceita **HTTP GET para download** e **HTTP PUT para upload** (conforme TR-143), com dados sintéticos e descarte do upload; sem PII.
- Servidor no core com rota a partir da WAN de serviço. Destino Internet **fora do domínio de roteamento do provedor**, com conectividade real e infraestrutura gerida/autorizada; não basta usar FQDN externo resolvido internamente.
- Capacidade útil comprovadamente acima do plano testado, monitoramento de CPU/interface/disco, sem CDN/cache/gzip; endereço/ACL fixos e sem auth que ONT legado não consiga enviar.
- Preferir nó que o provedor já controla. `reference-test-node` fornece protótipo de laboratório e **não deve ser colocado na Internet sem firewall, endurecimento e prova de carga**.

## Decisões por incompatibilidade
- Bridge/SFU sem interface IP de serviço: `UNSUPPORTED` para teste direto da ONT; não testar `MGMT` como proxy.
- ONT roteada sem TR-143: `UNSUPPORTED` neste P0; apenas registrar possibilidade futura de adapter nativo homologado.
- TR-143 presente mas sem permissão de escrita/firmware defeituoso: `PARTIAL/UNSUPPORTED` com causa; não burlar via shell.

## Idempotência, paralelismo e proteção
- Único teste ativo por ONT; **máximo 1 job simultâneo por PON** e 2 jobs por tenant por padrão, parametrizáveis. Sem identificação de PON, não liberar teste até aplicar um limite seguro equivalente validado na operação.
- Download e upload nunca simultâneos na mesma ONT neste P0.
- Idempotency-Key opcional, caso API existente tenha padrão próprio reutilizá-lo; sem duplicar um job ao reenvio.
- Sem agendamento noturno automático neste P0. Ação com permissão, auditoria, aviso de consumo de banda.
