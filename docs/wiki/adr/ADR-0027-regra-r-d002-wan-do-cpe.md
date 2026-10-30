# ADR-0027 — R-D002 v1: o que o CPE informa da sua WAN (sobre o `cpe_state`)

Status: Accepted | Data: 2026-10-30 | Owner: equipe

Relaciona-se a ADR-0024 (regras puras e versionadas), ADR-SD-002 (leitura de parâmetros do CPE) e `cpe_state` (PR 53, migração 0019).

## Contexto
O ADR-0024 deixou R-D002..R-D004 de fora até existir fonte de dados em vez de regras que chutam. O `cpe_state` passou a levar da LAB ao cloud, com dado real de uma ONT de bancada, o enlace e a conexão da WAN do CPE e o estado dos rádios Wi-Fi. A R-D003 (coletor silencioso) já existe como comportamento (`edge_silent`) e a R-D004 (ONU online sem Inform recente do CPE) precisa do instante do último Inform, que ainda não é coletado; ambas ficam fora.

## Decisão
1. **R-D002 v1** é uma função pura (`app/core/diagnostics.py`, mesmas regras do ADR-0024: sem relógio, banco, rede, LLM). Sujeito: `cpe`.
2. **Entradas** (gravadas na execução, então o replay não precisa de relógio): `links` e `connections` (listas de `{estado, fresh}`, uma por leitura, ordenadas; nenhum enlace é escolhido: o enlace é `Up`/`Down` só se TODAS as leituras são recentes e concordam; divergência ou qualquer leitura antiga é indeterminado; Codex rounds 3 e 4); `newest_age_seconds` e `oldest_age_seconds` das leituras de WAN; frescor POR LEITURA (até 1 h), nunca agregado por CPE (o cache guarda a última linha de cada conexão: uma leitura recente de uma não pode validar a leitura antiga de outra; achado do Codex, round 1); e contexto da ONU ligada: `onu_link` (`confirmed`/`none`), `onu_status`, `onu_fresh`. Só palavras de enum e números; nenhum serial nem dado de cliente.
3. **Veredito:** sem leitura → `unknown`. Alguma conexão RECENTE `Connected`/`Up` → `observed`. Qualquer conexão lida há mais de 1 h (podendo ainda estar estabelecida) → `unknown`; a ação sugerida é um refresh de leitura (R0). **Todas** as conexões lidas, todas recentes, em estado não estabelecido (`Disconnected`, `Unconfigured`, `Down`, `NotPresent`, `LowerLayerDown`, `Error`) → `inferred`, sempre `requires_human_confirmation`, com causa `wan_link_down` (enlace recente Down), `wan_session_down` (enlace recente Up, sem conexão estabelecida: sessão ou provisionamento) ou `wan_connection_down` (enlace não lido, antigo, `Initializing` ou `Unavailable`: nada se afirma sobre ele; Codex round 2). Estados transitórios ou desconhecidos (`Connecting`, `Dormant`, `Unknown`...) e a ausência de conexão lida nunca viram afirmação.
4. **A ONU só dá contexto** (só o dado observado: "a ONU vinculada aparece online / não aparece online na OLT", sem concluir nada sobre a camada de acesso; sem vínculo confirmado e fresco, "a ONU não foi considerada") e nunca muda o veredito ou a causa. O vínculo ONU↔CPE precisa estar `confirmed` por uma pessoa (ADR-0021).
5. **API:** `POST /diagnostics/runs` aceita `cpe_id` (ou `onu_id`, resolvido pelo vínculo confirmado) para regras de CPE; regra de PON não aceita `cpe_id` e regra de CPE não aceita `olt_id`/`pon_id` (422). Continua somente leitura: não abre incidente, não escreve estado, não publica evento, não chama a rede. Mesma flag `diagnostic_engine` e mesmas permissões.

## Consequências
- Hipótese e conclusão ficam separadas; "o CPE informa" é a fonte, não "o cliente está sem internet".
- Sem leitura recente o produto diz desconhecido, nunca zero. A leitura é sob demanda (job `refresh`, desligado por padrão), então com a leitura ativa desligada a regra devolve `unknown`.
- Mudar limiares, a lista de estados ou a janela de 1 h exige a versão 2; a v1 não é editada.
- Não feito: Wi-Fi nesta regra (rádio habilitado/canal não indica defeito sozinho), R-D003 como regra, R-D004, tela de troubleshooting para a R-D002.
