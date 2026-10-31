# Review checklist — Codex

## BLOCK
- [ ] Acesso direto ao GenieACS NBI pelo navegador/cloud
- [ ] Qualquer escrita sem permissão/tenant/auditoria
- [ ] URL de teste arbitrária ou SSRF
- [ ] Medição pela VLAN de gerência apresentada como WAN serviço
- [ ] `HTTP 200` da task tratado como teste concluído
- [ ] `Completed` antigo apresentado como atual
- [ ] Conflito/duplicação com módulos existentes ou regressão FiberCore 2.2
- [ ] Sem limites de PON/tenant/dispositivo
- [ ] Segredo ou PII em logs/fixtures/URLs
- [ ] Test Node externo aberto sem proteção

## WARN
- [ ] Falta de teste com CPE real no perfil principal
- [ ] Duração muito curta para medir pico com confiança
- [ ] Qualidade de resultado não classificada
- [ ] Sidebar com mais de 2 KPIs dominantes ou tela extra desnecessária
- [ ] Ausência de screenshot real e atualização de help center

## PASS
- [ ] Interface é a WAN de serviço e foi verificada
- [ ] GET/PUT e cálculos condizem com TR-143
- [ ] Down/up sequenciais com partial
- [ ] Worker limita carga com timeout sem retry ofensivo
- [ ] Graceful degradation/flag/rollback
- [ ] Tests e audit completos; API aditiva
