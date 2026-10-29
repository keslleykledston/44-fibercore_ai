# PRD incremental — FiberCore AI v2.2

## Objetivo
Converter dados de OLT, GenieACS (TR-069), controller USP (TR-369) e ERP em **contexto útil e decisão assistida**; minimizar tempo de triagem do humano. Adicionar capacidades sem prejudicar serviços existentes.

## Escopo P0
**Subscriber 360** mostra identidade canônica, ONU e OLT/PON/CTO, estado óptico, dados CPE, assinante/contrato e timeline; cada fonte tem `source_id`, `observed_at`, quality. **Capability Registry** guarda `vendor/model/firmware/protocol/operation` e status `identified/observed/certified`. **Customer Context API** retorna visão agregada read-only com entitlement por tenant. **Guided Troubleshooting** traz caminhos determinísticos por sintoma com evidência. **NOC Center** prioriza problemas e clientes afetados com suppression de collectors down.

## Escopo P1
**Network Explorer** tree-first, sem mapa compulsório; relação POP/OLT/PON/CTO/ONU com confiança e pendências. **Wi-Fi Experience** apresenta banda, qualidade, canal, RSSI/ruído/clientes conectados somente se expostos e recentes. **QoE** óptico e residência separados, com coverage e confidence. **Automation Studio** tem templates declarativos e dry-run; comandos escritos exigem certified+approval. **Help Center** contextual com screenshots reais e artigos PT-BR.

## Escopo P2
Copiloto multi-provider com ferramentas read-only e fontes; relatórios preditivos e campanhas de firmware/massive provision apenas após pilotos, perfil homologado e auditoria; portal do assinante somente após validação de valor/compliance.

## Personas
NOC N1 resolve triagem; NOC N2 investiga e propõe ações; Atendimento encontra cliente rapidamente; Campo opera CTO/ONU; ISP Admin aprova perfis e acesso; K3G Admin suporta com delegação; Auditor lê ações redigidas.

## Jornadas
1. Buscar serial/contrato → Subscriber 360 → confiança + fonte → guided diagnosis → próximo passo documentado.
2. PON com muitos offline → detectar janela comum → validar saúde do Edge → incidente agregador → notificar/atribuir.
3. ONU com bom sinal óptico e Wi-Fi ruim → sugerir investigação local de Wi-Fi (não afirmar culpa) → orientação para N1.
4. CPE dual-stack → preferir protocolo por capability certificada; serial/endpoint reconciliados; mutação concorrente bloqueada.
5. Workflow escolhido → preview/diff → validade e risco → aprovação externa de execução → pós-check.

## Regras de UX
Visual leve iOS-like com identidade própria; até 6 áreas de navegação. Busca global sempre acessível. Em um card nunca misturar estado do conector com status do CPE. Evitar dashboards com 10+ gráficos e métricas sem contexto. Detalhes apenas sob demanda.

## Requisitos não funcionais
RBAC/ABAC, RLS+auth, logs sem dados sensíveis, módulo degradado isolado, API versionada, histórico auditável, atualizações sem quebra contratual e docs local-first versionadas. Feature flags para lançamento gradual e fallback de UI.

## Não objetivos
Reimplementar GenieACS; substituir USP Controller por GenieACS; prometer suporte universal de firmware ou TR-369; fazer LLM executar comandos diretamente; criar scores com poucos dados; copiar designs de terceiros.

## Aceite
P0 testado com dois tenants e dados sintéticos, cross-tenant bloqueado, Subscriber 360 com provenance e stale, score 'insufficient_data' quando necessário, rules diagnostics testáveis, incidentes sem falso positivo com Edge down, tela com manual e screenshots de aplicação real revisados. Propor metas de desempenho/escala após benchmark.
