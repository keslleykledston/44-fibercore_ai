# Diagnóstico determinístico e QoE — design técnico

## Diag engine
**Inputs:** optical status, RX/TX normalized units, PON alarms, Edge health, ACS/USP session freshness, WAN/PPPoE state, Wi-Fi telemetry, ERP/contract state. Cada input com origin/time/quality. **Outputs:** `finding_id`, `status` (`observed`, `inferred`, `unknown`), hipótese, regra/versão, evidências, próxima ação de leitura, `requires_human_confirmation`.

## Exemplos de regras SEM limiares universais
- R-D001: várias ONUs na mesma PON offline em janela, com OLT/Edge coleta saudável → suspeita de falha coletiva de acesso; classificar PON e listar assinantes; confirmar com eventos e comportamento dos vizinhos.
- R-D002: CPE WAN ativa, optical normal segundo threshold homologado, Wi-Fi dados mostram retry/interferência → hipótese de qualidade local; não marcar problema físico PON sem evidência.
- R-D003: Edge unreachable, cached ONUs antigas → status stale e incidente da infraestrutura de coleta, **não** emitir dezenas de incidentes ONU offline.
- R-D004: ONU online óptica e CPE CWMP sem Inform recente → investigar ACS/CPE session/NAT e cobertura do controlador, não assumir assinante sem internet.

## Scores independentes
Optical Health usa indicadores disponíveis: Rx/Tx em limites **por equipamento/optics PON class certificado**, quedas/flaps, erro/alarme, estabilidade de sinais. Home Experience usa Wi-Fi RSSI/channel/utilization/associated clients (se expostos), WAN errors, latência/speed test medidos e contexto de perfil, separando congestionamento externo. Sem thresholds de fabricante presumidos.

Algoritmo v1 é **especificação paramétrica a homologar**: para métricas certificadas normalizar subscore 0–100, ponderar apenas métricas esperadas; score = soma(peso_i*subscore_i)/soma(peso_i válidos). Coverage = soma(peso_i válidos)/soma(peso_i esperados). Se `coverage < min_coverage` ou status stale, `score=null`, `status=insufficient_data`; mostrar métricas indisponíveis e data. Pesos, freshness TTL, tolerâncias e limiar mínimo devem ser aprovados em ADR e testados; NÃO fixar valores arbitrários em produção.

## Testes
Fixtures com medição ausente, outdated, contradictions TR-069/USP, Edge down, fonte parcialmente indisponível, óptica ruim + Wi-Fi bem, óptica bem + Wi-Fi ruim, thresholds por modelo, tenant isolation. Garantir score calculado só com evidências existentes e reprodutibilidade por algoritmo_version.
