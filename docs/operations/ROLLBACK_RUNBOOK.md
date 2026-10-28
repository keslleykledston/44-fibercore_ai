# Runbook de rollback e incidente de plataforma

## Se um módulo ficar unhealthy após deploy

1. Confirmar sintomas, blast radius, tenants, versão, causa e mudanças de schema. Não assumir que o Docker healthcheck reinicia container automaticamente.
2. Manter módulos saudáveis operando; ativar feature flag e isolamento do módulo defeituoso.
3. Suspender novos jobs de escrita em módulos degradados; não cancelar nem reexecutar cegamente jobs já aceitos.
4. Congelar rollout e direcionar novas requests à versão anterior quando compatível; em K3s usar deployment rollout undo se validado, em Compose trocar imagem digest explicitamente com janela de manutenção.
5. Verificar idempotência, outbox, NATS lag, jobs pendentes, CPE 202 e postchecks em andamento.
6. Se migração não for backward-compatible, não executar down sem aprovação: plano de compensação/restauração testado e janela.
7. Registrar timeline, RCA provisório e depois definitivo, métricas, evidência, decisão ADR e wiki.

## Se o GenieACS local estiver indisponível

- Edge NBI connector reporta degraded; suspender operações de escrita e mostrar último dado com timestamp; não reiniciar o GenieACS automaticamente nem tocar no Mongo preexistente sem autorização do ISP.
- Testar retorno apenas em modo leitura e reconciliar task status antes de submeter novas operações.

## Se o USP Controller estiver indisponível

- Isolar módulo USP, continuar TR-069/OLT, marcar fontes USP stale; evitar fallback write TR-069 sem política explícita porque pode haver ação conflitante pendente.

## Se o Edge cair

- expirar jobs conforme TTL, alarmar perda de heartbeat, preservar histórico read-only com selo staleness, proibir dispatch tardio de envelopes vencidos.
