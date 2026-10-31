# Codex — revisão de integração incremental QoS-001

Revise o diff produzido pelo Claude Code no FiberCore 2.2 à luz dos pacotes `SD-001 v1.0` e `QoS-001 v1.1`.

Prioridade absoluta: identificar duplicação de Speed Diagnostics, GenieACS/Edge, worker/job system, RLS, migrations, Capability Registry ou ONU 360. Procure regressões, stale results, geração de testes em WAN de gestão, falsos zeros, confusão de Wi-Fi PHY com throughput, interpretação arbitrária de níveis de RX, isolamento tenant e SSRF. Verifique HTTP 200/202 do NBI, confirmação do diagnóstico, idempotência, locks PON, flags/rollback e correlação por run.

Entregue relatório: `BLOCKER / HIGH / MEDIUM / LOW`, `arquivo:linha`, prova, correção mínima, testes adicionais e **GO/NO-GO** de canário. Use `checklists/CODE_REVIEW.md` e Q01–Q22. Não modifique produção sem autorização.
