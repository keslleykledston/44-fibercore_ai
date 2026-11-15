# ADR-0055: Leitura periódica da lista de ONTs a autorizar (autofind) na Huawei MA5800

Status: **Accepted e construída** (Edge + nuvem) | Data: 2026-11-14 | Owner: Claude Code (implementação), Codex (revisão)

Origem: ordem do responsável (2026-11-14): "construa o autofind e consulta a cada 10 min (se não pesar na OLT)". Complementa a ADR-0054 (leitura por pedido) e mantém a decisão de que a plataforma **só lista** candidatas: nada é autorizado nem removido.

## Decisão
**D1 — Coletor próprio, não carona na coleta.** A coleta completa da MA5800 percorre todas as PONs (dezenas de comandos, ~45 s) e roda a cada 15 min; subir isso para 10 min aumentaria a carga em 50%. O autofind é **um** comando. O Edge ganha o coletor `Autofind`, que abre uma sessão curta por OLT (login, `display version`, `enable`, `display ont autofind all`; no máximo 6 comandos e 256 KiB), e fecha.

**D2 — Opt-in por OLT, faixa limitada.** `autofind_seconds` na entrada da OLT (só perfil `huawei_ma58_r02x`): 0 = desligado (padrão); senão 300..3600. Fora disso a configuração é recusada. Recomendado 600 (10 min).

**D3 — Pacing próprio, trava compartilhada.** O coletor usa a mesma trava "em voo" do equipamento que a coleta e as manobras (nunca duas sessões juntas), mas guarda **o seu próprio** intervalo e cooldown (`<equipamento>#autofind`). Assim uma leitura a cada 10 min não empurra a janela de 15 min da coleta. O intervalo efetivo é `autofind_seconds` menos 30 s de folga (os ticks são sequenciais; sem a folga 10 min viraria 15). O coletor também **não age enquanto a coleta da mesma OLT está em cooldown** por falha (login recusado nunca é tentado por duas portas).

**D4 — Entrega.** O item `olt_autofind` (Gauge: a lista é o estado ATUAL, o item mais novo substitui os mais antigos da fila) vai para `POST /v1/edge/olt-autofind`. A nuvem exige token do Edge ligado ao `edge_id`, a OLT do próprio Edge, a flag `onu_discovery` (desligada: `202 ignored_feature_off`, nada guardado), leitura com no máximo 15 min (mais antiga: `202 ignored_too_old`, nada guardado; Codex 636, MEDIUM: um Edge de volta de uma queda reenvia lista velha) e o formato tipado fechado de `olt.autofind` (sem Password/Loid/Checkcode, sem chave extra; lista vazia é válida). Grava a leitura no cache como fonte `routine` (já prevista no esquema) e as observações `edge_read` na mesma transação. O sync por pedido e a tela de pendentes passam a aceitar `routine` além de `job`.

**D5 — O que não muda.** Só leitura. Uma ONT que sai da lista (alguém a autorizou, ou caiu) não é tocada: envelhece para `stale` em 1 h (a lista é o estado atual, mas a ausência não prova autorização). O layout COM entradas continua não observado na MA5800 (ADR-0054 D3): o parser falha fechado.

## Peso na OLT (por OLT, a cada 10 min)
1 login + 3 comandos de leitura curtos (versão, `enable`, lista), contra ~33 comandos e ~45 s da coleta completa a cada 15 min. Medição de CPU da OLT não existe; o limite de segurança é o orçamento fixo de comandos/bytes, o cooldown de 15 min após falha e a recusa de intervalos abaixo de 5 min.

## Fora desta decisão
Autofind em Datacom e Intelbras; autorizar ou remover ONT (ver ADR-0054).

## Provas
`go vet ./... && go test -race ./...` em `agents/edge` (coletor: leitura, pacing próprio sem mexer na coleta, cooldown, falha, driver sem leitor, layout desconhecido; config; driver); `tests/test_olt_autofind_push.py` (fila + cache + vazia válida, formato/OLT/Edge/tenant, flag desligada, isolamento).
