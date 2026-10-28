# Registro das revisões Codex (adversarial-review, escopo `--base main --scope branch`)

**Limitação de evidência:** as saídas brutas do Codex não foram persistidas em arquivos; este registro é um resumo do que foi retornado em cada rodada durante a sessão de 2026-10-27/28 e foi escrito por quem implementou. O gate real é reproduzível: `node <plugin>/scripts/codex-companion.mjs adversarial-review --wait --base main --scope branch "<foco>"` sobre cada branch (a branch fica no GitHub).

| Branch / PR | Rodadas | Resultado final | Achados relevantes corrigidos |
|---|---|---|---|
| sprint0/01-foundation | 2 | approve | role de runtime preexistente sem endurecimento (critical); OpenAPI vs rotas |
| sprint0/02-outbox-jetstream | 6 | approve | retenção 7d perdia eventos; replay dentro da janela de dedupe; ensure_streams idempotente; limites preservados no restart; (1 falso positivo de unidade refutado por teste) |
| sprint0/03-edge-fleet-mocks | 5 | approve | credencial de edge não ligada a um edge; downgrade; status/revogação por runtime |
| sprint0/04-supply-chain-backup | 8 | approve | restore destrutivo; permissões/cifra de backup; sobrescrita; publicação atômica; .gpg |
| sprint1/05-inventory-ingestion | 4 | approve | posse de CPE por edge; FK composta ONU/PON; lote/limites; corrida; snapshot CPE obsoleto |
| sprint1/06-edge-go | 3 | approve | fila sem limites; persistência de rodada; backpressure por tipo |
| sprint1/07-olt-drivers | 3 | approve | orçamento agregado por OLT; coleta fora do loop de heartbeat; orçamento de comandos |
| sprint2/08-customers-csv-associations | 2 | approve | leitura incremental do CSV; aprovação concorrente |
| sprint2/09-noc-incidents | 4 | approve | correlação por seriais; serialização; snapshot parcial; alertas no SQL |
| sprint3/10-job-gate | 3 | approve | Idempotency-Key ASCII; resultado de job durável/idempotente |
| addendum/11-v2.1-foundation | 2 | approve | proxy apontava para `web` inexistente |
| web/12-scaffold | 2 | approve | /v1/auth/workspaces sem checar conta ativa |
| hardening/13-login-throttle | 4 | approve | lockout atômico; throttle por IP serializado; retenção; IP do cliente via BFF |
| web/14-assinantes-operacoes | 3 | approve | limite de upload antes do multipart; paginação de sugestões |
| final/15-handoff | em curso | — | honestidade da documentação (este arquivo e TEST_EVIDENCE) |

Riscos aceitos e documentados (não corrigidos): DoS direcionado por lockout de conta (KNOWN_ISSUES); postcss embutido no Next (build-time).
