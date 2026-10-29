# Plano de adoção sobre build existente

1. Inventariar estado do repo: arquivos, migrations, OpenAPI, roles, serviços Docker, módulos e telas existentes; salvar SHA e branches. **Não atualizar dependências grandes simultaneamente com refatoração v2.2.**
2. Gerar matriz de compatibilidade para cada novo endpoint/schema; evitar colisões com `/v1/onus`, `/v1/cpes`, `/v1/customers`. Manter prefixo público `/api/v1` via reverse proxy e `/v1` no core conforme baseline.
3. Adicionar ADR de projeção Subscriber 360, ADR de Quality/Freshness, ADR de score e ADR do registry; solicitar aprovação humana sobre alterações com impacto.
4. Introduzir tabela e migrations em modo expand (nullable/new tables), backfill controlado com cursor e monitoramento; contract only após janela e evidência.
5. Publicar funções behind flags: P0 inicialmente dev/stage e tenants de laboratório. Falha nos novos módulos deve devolver partial/stale e preservar API legacy.
6. E2E regressão funcional e segurança multitenant em cada PR. Validar docs/screenshot. Canary e rollback feature flag; restaurar snapshots se migration comprometer dados.
7. Somente após aceitação de dados reais homologados liberar coleta contínua; ações de rede ficam bloqueadas até policy/homologação.

## Checklist de conflitos
Campos de estado (offline vs stale), timezone, source ID, identity ONU/CPE/associado, jobs duplicados, versão API, controller CWMP/USP, dados de ERP, permissões por persona, densidade visual e rotas da ajuda.
