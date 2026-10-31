# Integração técnica (não alterar macroarquitetura)

## Caminho de dados autorizado
```text
OLT/driver via Edge read-only ----> normalizador/cache FiberCore ------┐
GenieACS NBI via Edge ------------> adapter ACS FiberCore -------------┤
USP adapter (futuro) -------------> adapter USP FiberCore -------------┤
ERP/associação (se existente) ----> view autorizada FiberCore ---------┤
                                                                     ▼
                                            View-model/seletores existentes (tenant/RBAC)
                                                                     │
                                                                     ▼
                                  ONU Quick Inspector / DeviceSummary / StatusPill
                                                                     │
                                                                     ▼
                                               navegação para ONU/ONT 360°
```

## Pontos de integração no frontend
1. `AppShell` permanece; localizar o `EntityDetailDrawer` e estender variante/slot ONU. Se não existir em código real, criar um equivalente mínimo dentro do frontend atual, sem nova dependência pesada.
2. Componente de seleção deve fornecer `selectedOnuId` + autorização da rota atual e callback `onClose`.
3. Consumir hook/query/cache já utilizado no `ONU 360°` e inventário. Separar observação de PON e estado ACS.
4. Se backend já expõe summary, adaptar os campos pelo mapper validado. Evitar duplicar lógica e criar endpoint novo.
5. Guardar na cache chaves incluindo tenant, ONU e escopo; limpar seleção ao trocar tenant.
6. Abortar fetch ou ignorar resposta antiga ao selecionar outra ONU. TTL/freshness devem ser os da fonte, sem polling novo agressivo.
7. Manter back/forward e busca/filtros da lista. Fechar via teclado e botão.

## Caso seja tecnicamente necessário compor resumo no servidor
**Somente após** inspecionar contratos e comprovar o problema de N+1 ou autorização: propor read-only `GET /api/v1/onus/{id}/quick-summary`, utilizando os serviços existentes. Schema ilustrativo em `04_contracts/`. Endpoint não está aprovado, não pode ser criado automaticamente.

Resposta deve refletir: `onu` (identidade), `pon` (estado OLT), `acs` (estado de gestão), `optical` (RX e severidade *pré-normalizada*), `association` (cliente e confiança com RBAC), `visual` (template genérico/homologado), `capabilities`, `timestamps` por dado.

## Rotas
- `ONU 360°`: descobrir rota canônica real via código/Next.js router. Não substituir por URL presumida.
- `help_slug`: usar slug real do artigo contextual na Central de Ajuda `/ajuda/<slug>`.
- `returnTo`: aceitar apenas path relativo/rota interna validada; não aceitar URL arbitrária.

## Integridade e observabilidade
- Logar `device_id`, fonte, `loading/error/stale` e duração agregada sem payload de cliente/segredos.
- Medir tempo de abertura, falha de carga, latência de composição, render por troca ONU.
- Se integrações opcionais caírem, renderizar seção parcial e manter identidade/OLT quando possível.
- Nenhum comando SSH, write ACS, provisionamento ou credencial expostos pelo drawer.

## Compatibilidade com kit v2.2
Next.js/React/TypeScript, shadcn/Tailwind; Backend FastAPI, normalização via Edge; GenieACS e host existente não devem ser instalados/migrados; TR-369 futuro adapter; multi-tenant/RLS; NATS/outbox atuais não devem ser recriados para uma interface.
