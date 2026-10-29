# ADR-0024 — Regras de diagnóstico determinísticas: funções puras, versionadas e reproduzíveis

Status: Accepted | Data: 2026-10-29 | Owner: equipe

Relaciona-se a FC22-006, ADR-0018 (correlação de PON) e `docs/engineering/DIAGNOSTIC_AND_QOE.md`.

## Contexto
A única regra de diagnóstico (`pon_mass_outage`) vivia dentro do fluxo de ingestão (`noc.py`), misturada ao ciclo de vida do incidente. Não havia como executá-la sob demanda, versioná-la nem provar depois por que ela concluiu o que concluiu.

## Decisão
1. Uma regra é uma **função pura** `entradas JSON -> achado` em `app/core/diagnostics.py`: sem relógio, banco, rede, aleatoriedade, LLM, e sem escrita em equipamento. Um teste (AST) impede importar qualquer coisa fora da biblioteca padrão pura.
2. **Versionamento append-only**: regra = (id, versão). Comportamento novo = versão nova; versões antigas continuam registradas para que execuções antigas possam ser reavaliadas.
3. **R-D001 v1 é extraída sem mudar comportamento**: o correlator de incidentes passa a chamá-la para a decisão de abrir; um teste de propriedade compara 2000 casos com a fórmula original e a suíte do NOC é a regressão. (A parte com estado — resolver, expirar, membros — continua no correlator; só a decisão de padrão foi extraída.)
4. **Achados** têm status `observed` (fatos medidos), `inferred` (hipótese derivada; sempre `requires_human_confirmation`) ou `unknown` (dado velho/ausente: nada é afirmado). Sem score, sem valor imputado.
5. `POST /diagnostics/runs` é **somente leitura**: lê o estado já coletado, não abre incidente, não chama a rede. Persiste em `diagnostic_runs` (append-only; a app só `INSERT/SELECT`) a regra+versão, as **entradas exatas** e os achados. `GET /diagnostics/runs/{id}` devolve `reproducible`: reavaliar as entradas gravadas com a mesma versão dá os mesmos achados (adulteração é detectada).
6. Frescor e janela relativa são **gravados nas entradas** (`reference_at`, `fresh_data`): o replay não precisa de relógio. Limite de 200 PONs por execução, com `truncated`.
7. Flag `diagnostic_engine` (ADR-0023), desligada por padrão; permissão `diagnostics:run` (isp_admin, engineer, noc_n2); leitura com `incidents:read`.

## Consequências
- R-D002..R-D004 dependem de dados ainda não coletados (Wi-Fi/WAN, sessão ACS): ficam fora até existir a fonte, em vez de regras que chutam (ADR-0022).
- Completude da PON não é persistida: uma PON sem padrão é `observed` ("os quedas recentes não atingem o padrão"), nunca "a PON está saudável".
- Mudar limiares da R-D001 exige a versão 2; a v1 não é editada.
