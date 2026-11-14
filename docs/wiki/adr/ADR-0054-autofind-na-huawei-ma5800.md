# ADR-0054: Lista de ONTs a autorizar (`olt.autofind`) na Huawei MA5800

Status: **Accepted e construída** (Edge + nuvem) | Data: 2026-11-14 | Owner: Claude Code (implementação), Codex (revisão pendente)

Origem: pergunta do responsável (2026-11-14) sobre três capacidades nas OLTs que já comunicam: ONT offline, ONT disponível para autorizar e limpeza de PON. Offline já existe (coleta de 15 em 15 min, `GET /v1/onus/offline`). Autorizar e limpar não existiam fora da Huawei MA5600 R015. Esta decisão cobre **somente a leitura** da fila de ONTs aguardando autorização nas duas MA5800 (ARAUJO e JGA). Nada de escrita.

## Decisão
**D1 — Um comando, só leitura.** `display ont autofind all` entra na allowlist exata do perfil `huawei_ma58_r02x`. A consulta `olt.autofind` roda na sessão que a coleta já abriu (depois do `enable` do snapshot), com a mesma reserva, intervalo, lease assinado e orçamento da ADR-0029.

**D2 — Captura real (2026-11-14, R022C11 e R024C11).** Com nada aguardando, as duas respondem `Failure: The automatically found ONTs do not exist` (o mesmo texto vazio da MA5600 R015). O MA5800 antecede a resposta com um bloco `Command:` + o comando repetido; o driver o remove antes de entregar o texto ao parser. A fixture `display_ont_autofind_all_empty.txt` é essa captura (não tem serial nem IP).

**D3 — Lista com entradas NÃO foi observada nesta família.** O parser é o mesmo da R015 (`parseAutofind`): aceita só o layout verificado (régua, rótulos, rodapé com contagem igual às entradas) e falha fechado (`bad_output`) em qualquer outro. Os testes com entrada reutilizam a fixture sintética da R015. Quando uma ONT real aparecer numa MA5800, é preciso capturar e confirmar o layout antes de chamar o perfil de `observed`. Senha, Loid e Checkcode nunca são lidos (igual R015).

**D4 — A MA5800 não tem catálogo.** Responde só `olt.connection` (ADR-0053) e `olt.autofind`. Qualquer outra consulta termina sozinha com `query_not_enabled` no Edge e a nuvem a recusa antes (`422 vendor_not_supported`). A nuvem reconhece a MA5800 pelo firmware `MA5800V100R02*` (o modelo não distingue: fixtures usam `MA5800-X7` com catálogo). Datacom e Intelbras seguem só com `olt.connection`.

**D5 — `quit` deixa de ser enviado ao fim da coleta MA5800.** Ele é respondido com `Are you sure to log out? (y/n)[n]:` e o shell nunca responde pergunta: o prompt ficava pendente e se colaria ao próximo comando da mesma sessão (as consultas). Fechar o canal SSH encerra a sessão. `quit` saiu também da allowlist.

## Decisão do responsável (2026-11-14)
Neste momento **nada é removido nem autorizado pela plataforma**: quem atua é o agente humano, e a plataforma só **lista as ONUs candidatas** (fila de `rede/pendentes`, `authorization: not_available`). A flag `onu_discovery` foi ligada nas 5 organizações da LAB para isso. A leitura é por pedido (`olt.autofind`, depois "Atualizar a partir da última leitura do Edge"); uma leitura com mais de 1 h é recusada (`read_too_old`), então a lista só é atual quando alguém pede a leitura. Leitura periódica automática não foi construída.

## Fora desta decisão
- Autorização de ONT e remoção/limpeza de PON (escrita em equipamento de cliente: política, preview, aprovação, pós-check, auditoria; ADR própria).
- Autofind em Datacom e Intelbras (falta capturar o comando de ONU não provisionada de cada um).
- Causa de queda em Datacom e Intelbras.

## Provas
`go vet ./... && go test -race ./...` em `agents/edge`; `tests/test_olt_connection_multivendor.py`, `test_olt_query.py`, `test_onu_discovery.py`. Teste real nas duas MA5800: ver o resultado registrado no runbook.
