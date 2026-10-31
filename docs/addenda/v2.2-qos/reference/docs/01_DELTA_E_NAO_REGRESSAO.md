# Delta de escopo: aditivo ao SD-001

## Base de referência
- **Produto:** FiberCore 2.2 / plataforma modular atual.
- **Implementação antecedente:** SD-001 — Speed Diagnostics TR-143, versão do handoff 1.0, arquivo e hash no README.
- **Arquitetura-alvo (a confirmar no repositório):** GenieACS existente → Edge Connector outbound → orquestração/jobs existente → Capability Registry → ONU 360/EntityDetailDrawer → Central de Ajuda → Copilot read-only.
- **Não é verdade assumida:** arquivo, endpoint, interface, banco, framework, stage de TR-369 ou nomenclatura do repositório; o agente precisa localizar e confirmar.

## Matriz da mudança
| Componente | Estado SD-001 | Adendo QoS-001 | Proibido |
|---|---|---|---|
| GenieACS / NBI | Já integrado/previsto via Edge | Reusar `getParameterValues`, `refreshObject`, `setParameterValues` | Instalar outro ACS ou expor NBI |
| Edge Connector | Canal seguro existente | Estender comandos de leitura/diagnóstico com autorização | Criar túnel paralelo |
| Capability Registry | Detecta suporte TR-143 | Acrescentar `PING`, `DNS`, `TRACE`, `OPTICAL`, `ETH`, `WIFI`, `CPU`; por modelo+firmware | Assumir que marca = suporte |
| SD-001 Speed Runs | download/upload CORE/INTERNET | **Referenciar IDs dos runs** nos diagnósticos completos | Recriar motor TR-143, DTO e nó de teste |
| Diagnostic Engine / fila | Motor existente | Adicionar tipo/suite quality e subjobs leves | Criar outra fila/worker |
| ONT Drawer | Testar banda | Cartão `Qualidade do serviço` com RÁPIDO e COMPLETO | Criar outra página/tela 360 |
| Inventário/Monitoramento | Existente | Reusar estado e leituras recentes, com fonte e timestamp | Poluir banco com cópias de inventário |
| Copilot | Interpreta informações | Hipóteses com evidência e grau de confiança | Manobra ou teste autônomo |
| TR-369 | Arquitetura futura/atual do projeto | Nenhuma migração; respeitar mesma interface de diagnósticos caso já exista | Construir novo USP controller |

## Canais de integração e semântica
- **RÁPIDO:** somente telemetria de leitura + poucos testes IP leves autorizados. Se sem suporte a ping/DNS, não bloquear toda a execução; preencher `not_supported` / `not_available`.
- **COMPLETO:** agrega RÁPIDO + uma sequência *controlada e aprovada* de SD-001 para CORE/INTERNET selecionados + traceroute opcional. Não reexecutar SD-001 se já em andamento na mesma ONT; fila/concorrência compartilhada.
- **PON/OLT:** se a leitura óptica vem da OLT via outra integração, declarar `source=OLT_ADAPTER`, não `TR069`. Não inferir óptica da PON só por `Device.Optical` presente.
- **Métricas Wi-Fi:** taxas PHY não são velocidade de internet; não usar como speedtest.

## Gate da execução
1. Artefatos `CURRENT_STATE.md` e `GAP_MAP.md` no repositório/PR, com caminhos comprovados.
2. Identificar pontos de extensão mínimos e contratos existentes; caso haja rotas de diagnóstico genéricas, usá-las.
3. PRs pequenas, sem exclusão/renomeação de componentes alheios.
4. Flag QoS independente do SD-001 (o SD-001 ainda pode operar sem QoS).
5. Versionamento de adaptadores/vendor e controle de migrações aditivas.
