# Decisões de produto + dependências

**D-01**: A experiência é o *Quick Inspector* do dispositivo selecionado. Não substitui `ONU/ONT 360°`; detalhes extensos continuam na página existente.

**D-02**: Um único painel contextual à direita. O sistema centraliza a seleção e nunca empilha o Quick Inspector com drawer de incidente/copiloto (usar região única, trocar conteúdo ou fechar um antes de abrir outro).

**D-03**: PON online/offline (OLT) é **independente** de contato ACS; `unknown`, `stale` e `connector_unavailable` têm aparência e texto próprios.

**D-04**: Miniatura tem duas camadas: ilustração genérica default e mapeamento de LEDs/portas opt-in quando o vendor/modelo/firmware estiver homologado. Não inferir LOS físico de ACS offline.

**D-05**: Dados de cliente/contrato dependem de mapeamento validado + permissão do operador. `confidence=conflict/low/unassociated` não atribui cliente como fato.

**D-06**: Nenhum campo novo se torna obrigatório para abrir o sidebar. Exibir `Não disponível` quando coleta/driver/capability não suportar dado.

**D-07**: No desktop largo, considerar drawer 360–400px não modal e conteúdo central fluido; no médio/móvel usar sobreposição modal acessível; não causar scroll horizontal.

**D-08**: Não criar endpoint novo por padrão. Preferir cliente e consultas já existentes; só propor `GET /api/v1/onus/{id}/quick-summary` se composição existente gerar N+1 relevante, com aprovação de contrato e testes multi-tenant.

**D-09**: Feature flag `ui.onuQuickInspector` ou equivalente existente, default OFF até QA/gates. Fechar flag preserva funcionamento original.

**D-10**: `Investigação`/IA é link contextual somente se existir fluxo real, capacidade e permissão; caso contrário ocultar, não renderizar CTA decorativo.

## Dependências não bloqueantes
- SVG real de cada fabricante: usar genérico.
- HubSoft: mostrar vínculo apenas se dados confiáveis existirem, senão `Sem vínculo confirmado`.
- USP/TR-369: opcional enquanto não homologado.
- WebSocket: não necessário, atualizar via mecanismo de freshness/cache existente.
- LLM: nenhuma dependência no MVP desse adendo.

## Precedência
Segurança e contratos > ADRs vigentes > PRD 2.2 > API v2 > este adendo > exemplos. Registrar conflito como decisão pendente no PR, sem sobrepor arquitetura.
