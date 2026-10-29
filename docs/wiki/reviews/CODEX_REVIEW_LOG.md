# Registro das revisões Codex (adversarial-review, escopo `--base main --scope branch`)

**Limitação de evidência (relato NÃO verificável por artefatos):** as saídas brutas do Codex não foram persistidas em arquivos; este registro é um resumo do que foi retornado em cada rodada durante a sessão de 2026-10-27/28 e foi escrito por quem implementou. O gate real é reproduzível: `node <plugin>/scripts/codex-companion.mjs adversarial-review --wait --base main --scope branch "<foco>"` sobre cada branch (a branch fica no GitHub).

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
| feat/37-onu-cpe-links-customer-context (PR 37, FC22-004) | 5 | approve | (saídas brutas em `raw/37-*-round1..5.txt`) CHECK de evidência no banco (+ bug de NULL no CHECK), RLS provada por relação, ambiguidade com a mesma normalização do match, contexto limitado a 50 ONUs, N+1 em lote, contagem real de sugestões; contestado/documentado: flags independentes por desenho |
| feat/38-subscriber-360 (PR 38, FC22-005) | 3 | approve | (brutos em `raw/38-*`) lista de clientes sem busca/paginação (API ganhou `offset`/`q` com curingas literais; auditoria sem o texto); dependência de flags (UI exige `subscriber_360` e `customer_context`) |
| feat/39-diagnostic-rule-engine (PR 39, FC22-006) | 1 | approve | (bruto em `raw/39-*`) sem achados; a extração é coberta por teste de propriedade (2000 casos) e pelos 29 testes do NOC sem alteração |
| feat/40-guided-troubleshooting (PR 40, FC22-007) | 5 | approve | (brutos em `raw/40-*`) estado de ONU desconhecido virando 'fora do ar'; ticket com documento e sintoma como fato; proveniência em conflito afirmando estado; execução antiga/de outra PON aceita como atual (agora por `pon_id` estável e ≤ 15 min) |
| feat/41-ac-validation (PR 41, FC22-008) | 3 | approve | (brutos em `raw/41-*`) a matriz citava testes que não sustentavam 'snapshot velho' (parcial ≠ velho; queda encerrada ≠ queda ativa): corrigido, +1 teste novo com mutante |
| feat/42-noc-command-center (PR 42, FC22-009) | 4 | approve | (brutos em `raw/42-*`) prioridade aplicada depois do limite (agora antes, com varredura dos abertos e `truncated`); classificação de Edge silencioso limitada a 100 (agora todos); contestados com evidência: `edge_id` NULL (coluna NOT NULL) e impacto oculto na ordem (nunca entra) |

Riscos aceitos e documentados (não corrigidos): DoS direcionado por lockout de conta (KNOWN_ISSUES); postcss embutido no Next (build-time).

| feat/edge-olt-cli-pacing (PR 43) | 6 | approve | (brutos em `raw/43-*-round1..6.txt`) estado do guard perdido no restart (agora persistido antes da E/S, reserva pessimista); chaves CLI×SNMP distintas (agora host canônico, config recusa duplicata, IP literal); dois processos (lock por diretório de estado); arquivo `null`/corrompido esfria qualquer transporte; timestamps absurdos normalizados e persistidos. Aceito/documentado: dois Edges em diretórios diferentes no mesmo host não são detectáveis (regra operacional: um Edge por OLT). |
| feat/edge-olt-observability (PR 44) | 2 | approve | (brutos em `raw/44-*`) o orçamento de tempo por OLT começava depois do login; agora cobre a abertura da sessão (CLI e SNMP), teste com login travado |
