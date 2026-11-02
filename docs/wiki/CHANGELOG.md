# Changelog

## Unreleased — H5 `onu_reauthorize` executada na bancada e `olt.autofind` validado (2026-11-02)
- Bancada (ADR-0030, H5): ciclo completo `undo service-port` → `ont delete` → autofind → `ont add` → `service-port` na ONU de bancada Huawei, **passou na 4ª tentativa** (job `97046bd6`, pós-check do Edge igual ao baseline). As 3 primeiras acharam defeitos reais (campos recuados, autofind lido uma só vez, eco quebrado em 80 colunas); duas deixaram a ONU sem service-port, reposta à mão. Evidência em `docs/wiki/bench/H5-onu_reauthorize-ma5608t-2026-11-02.md`; emenda no ADR-0030. Capacidade segue `identified` (falta o aceite do responsável).
- Edge: `joinWrappedEcho` (eco de comando longo quebrado em 80 colunas, só na primeira linha e só em coluna de quebra), autofind em polling limitado, `command timeout` informa o fim da tela. Codex approve (r2, r1 e r4 nas três frentes).
- `olt.autofind` **validado** (lista vazia e uma entrada reais): parser tipado fechado no Edge, forma tipada e `ROLLOUT` na nuvem, fixture sintético no layout real; `Password`/`Loid`/`Checkcode` nunca lidos. Layout de várias entradas NÃO observado (falha fechada pelo rodapé). Ainda sem ingest `edge_read` no `onu_discovery`.
- `onu_discovery`: `POST /v1/olts/{id}/onus/unregistered/sync` transforma a última leitura de `olt.autofind` em avistamentos `edge_read` (autoritativos; idempotente por leitura; serial ausente envelhece, não é apagado); botão em `/rede/pendentes`, que mostra a idade da leitura (do servidor: `asked_age_seconds`, aditivo em `olt_cache.latest`) e nunca afirma "nada pendente" sem leitura recente. Codex approve r6.
- NOC: o aviso de Edge silencioso agora tem **Diagnosticar este Edge (R-D003, somente leitura)** e mostra há quanto tempo o Edge não dá sinal e quantas leituras de ONU dele estão velhas (o alerta ganhou `edge_id`, aditivo). Achado lido em formato fechado; texto só da evidência. Codex approve r1. Sem e2e de navegador (a pilha efêmera não tem Edge silencioso no seed).
- ONU 360° mais enxuta: com a identificação do alto (flag `onu_quick_inspector`), os cartões Estado e Localização deixam de repetir Status, Rx, idade, OLT e PON; com a flag desligada a tela é a de antes (spec de recuo). e2e funcional + aparelho 73 passaram; Codex approve r2.

## Unreleased — inventário de perfis da OLT, sync edge_read e revisões imutáveis (2026-11-02)
- Captura supervisionada na OLT real (ADR-0032 lote 3, só leitura, autorizada pelo responsável): `olt.profile.line/srv/dba/traffic` capturadas, parsers estritos conferidos contra a saída real (41/34 perfis, DBA, 14 tabelas de tráfego; a saída crua foi apagada no Edge e na cópia local) e fixtures sintéticas com o mesmo layout. Rodam só em `MA5600V800R015C00` exato. Nome de perfil (texto livre do operador) vai nulo à nuvem salvo opt-in do dono do Edge (`olt_profile_names_to_cloud`).
- `POST /v1/olts/{id}/profiles/sync`: a última leitura DBA vira snapshots `edge_read` PARCIAIS (só o que a leitura afirma); idempotente, serializado por OLT, idade pela hora da pergunta, perfil ausente vira snapshot `unknown`. Codex approve r6.
- FC251-08: publicar revisão imutável de um rascunho (migração 0042, `profiles:publish`, maker-checker, simulação obrigatória, tela e e2e). Codex approve r2. Nada é enviado à OLT.
- Envelope do relay com `source`/`quality` (aditivo; schema próprio `contracts/event-envelope.schema.json`; não afirma conformidade com o v2.2). Codex approve r2.

## Unreleased — fila de ONUs aguardando autorização (v2.5, FC25-01/02/03, 2026-11-02)
- API (flag **`onu_discovery`**, desligada por padrão; permissões `discovery:read` (administrador, engenheiro, NOC N2) e `discovery:import` (administrador, engenheiro)): migração **0041** `onu_discovery_observations` (RLS forçada; o app só faz SELECT/INSERT e UPDATE de `last_seen_at`/`seen_count`/`vendor_hint`; sem DELETE; a origem faz parte da chave, então importação manual ou fixture **nunca renova** o que o Edge leu da OLT). `POST /v1/olts/{id}/onus/unregistered/import` (idempotente; `edge_read` reservado ao Edge), `GET /v1/olts/{id}/onus/unregistered` e `GET /v1/discovery/onus`. Condições: `new`, `waiting`, `stale` (dado antigo, nunca "offline") e `conflict` (serial já registrado ou visto em outra OLT/PON). Associação ERP sempre `unavailable` e autorização `not_available`. Nenhum job, evento ou incidente é criado.
- Web: `/rede/pendentes` (filtros, origem, motivos, registro à mão) e atalho **ONUs pendentes** na Rede; some com a flag desligada (404). Seed sintético, e2e `pendentes.spec.ts` + recuo, capturas reais e how-to `rede/onus-pendentes`. Suíte da API: 993 passam.
- Pendente (depende de ordem/supervisão): leitura real `olt.autofind` e associação ERP por serial.

## Unreleased — Profile Studio: telas, seed e ajuda (v2.5, ADR-0040, 2026-11-02)
- Web (flag `profile_studio`, desligada por padrão; desligada, `/rede/perfis` é 404 e o atalho **Perfis da OLT** some): `/rede/perfis` (OLTs, inventário com origem/situação/certificação, importar à mão, criar rascunho como cópia) e `/rede/perfis/[id]` (editor **Assistido** por campo e **Especialista** em JSON tipado, salvar com `If-Match` — a segunda aba é recusada, nada é sobrescrito —, comparação semântica campo a campo e simulação por OLT com "Escritas: 0 / não executável / reproduzível"). BFF fechado em `/bff/perfis/*` (same-origin, UUID, campos fechados, códigos de erro estáveis). Importação manual é sempre `manual_import` (nunca autoritativa). Não existe botão de aplicar.
- Seed sintético: flag ligada só no tenant demo, dois perfis fictícios e certificação SINTÉTICA da leitura de perfis só para a OLT demo (a OLT real do laboratório NÃO é certificada).
- Prova: e2e real `perfis.spec.ts` (fluxo completo + conflito de duas abas + axe sem violações sérias) e recuo `perfis-flag.spec.ts` com a flag desligada; capturas reais e how-to `rede/perfis-olt` (`validate_help.py` PASS).

## Unreleased — Profile Studio: migração 0040 e API somente leitura (v2.5, ADR-0040, 2026-11-02)
- Banco (migração **0040**, aditiva, reversível com `DROP TABLE`): `olt_profile_snapshots` (evidência **imutável**: o papel da aplicação só faz `SELECT`/`INSERT`; vendor/modelo/firmware da OLT, impressão digital calculada no servidor, texto de CLI importado sanitizado e escapado), `profile_drafts` (cópia editável com `row_version`; escopo e origem fixos; sem `DELETE`) e `profile_dry_runs` (append-only: entradas, planos e hashes). RLS forçada nas três.
- API (`apps/api/app/api/profile_studio.py`, flag **`profile_studio`** desligada por padrão; permissões novas `profiles:read` (isp_admin, engineer, noc_n2), `profiles:import` e `profiles:edit` (isp_admin, engineer)): `POST /v1/olts/{id}/profiles/import`, `GET /v1/olts/{id}/profiles` (o snapshot mais novo de cada profile, com a idade de AGORA e se a leitura do driver é certificada), `GET /v1/profile-snapshots/{id}`, rascunhos por **clone** de um snapshot (`POST/GET /v1/profile-drafts`, `PATCH` com `If-Match`: 428 sem ele, 412 se mudou), `POST .../compare` (diff semântico) e `POST .../dry-run` (um plano por OLT: reuse, adopt, clone, migração planejada ou bloqueado, com diff, impacto e `plan_hash`; **zero escritas**, `executable: false`) e `GET /v1/profile-dry-runs/{id}` (`reproducible` e `expired`). A leitura do driver só conta como certificada com uma linha `olt_profile_read` (suportada e observada/certificada) no registro de capacidades; sem ela nada é equivalente, reutilizado nem clonado. Alvo de outro fabricante/modelo/firmware que o do rascunho fica `target_out_of_scope`. **Importação manual ou fixture NUNCA sustenta reuso, adoção ou migração** (`snapshot_not_authoritative`): só uma leitura do leitor certificado (`source = edge_read`, ainda não entregue) é autoritativa; o clone continua possível (não escreve e não precisa de prova). A certificação de leitura vence em 90 dias sem nova verificação. Nenhuma rota abre job, publica evento, escreve na OLT nem usa o GenieACS.
- Testes: 11 novos de API (importação manual nunca autoritativa, certificação vencida, flag/permissão, snapshot imutável e inerte, recusas do modelo tipado, frescor de agora, isolamento entre provedores, ETag/If-Match, comparação, dry-run por OLT reproduzível e sem efeitos, fonte alterada); 984 passed no total. RBAC e contrato (96 caminhos) atualizados.

## Unreleased — núcleo do Profile Studio (v2.5, ADR-0040, 2026-11-02)
- API (`apps/api/app/core/profile_studio.py`, módulo PURO: sem relógio, banco, rede nem aleatoriedade): modelo **tipado e fechado** do profile de serviço da OLT (campos DBA, T-CONT/GEM, VLAN, tagging, QoS, portas, multicast, descrição; chaves de comando/script/segredo recusadas em qualquer profundidade; `vendor_extensions` só com esquema aprovado); `validate_settings` (por capacidade do driver, sem descartar campo em silêncio); `normalize`; `semantic_diff` por campo (`EQUAL/CHANGE/ADD/REMOVE/NOT_OBSERVABLE/UNSUPPORTED/CONFLICT`: campo não reportado nunca é igual, `tagged` ≠ `translation`, `assured` ≠ `maximum`, ausente ≠ `None`); `resolve_binding` por alvo (`reuse_exact`/`adopt_reference`/`clone_new_revision`/`plan_migration`/`blocked`, em ordem fixa e falhando fechado: observação velha, parcial, de outro tenant/OLT, firmware ou placa diferentes, fonte alterada, referências desconhecidas); `in_place_allowed` sempre falso; `plan_hash` (qualquer mudança depois da prévia muda o hash); `dry_run` com um plano independente por OLT e zero escritas; `sanitize_evidence` (texto de CLI importado vira texto puro, sem ANSI/controle/bidi e **escapado para HTML**). Campo obrigatório que nenhum dos lados traz é `NOT_OBSERVABLE` (ausente nos dois não é igual); rascunho inválido ou alvo de outro tenant ficam `blocked` e o tenant do alvo entra no `plan_hash`. Nenhuma rota, tabela ou flag ainda: o próximo PR liga isto a migração e API. 51 testes (inclui propriedade com 1500 casos e verificação de que o módulo não importa relógio/rede/aleatoriedade); 972 passed no total.

## Unreleased — v2.5 incorporado: GAP, ADR-0040 e backlog conciliado (2026-11-02)
- Docs: o pacote **FiberCore AI v2.5 COMPLETO** (OLT Provisioning, Profile Studio e Modo Especialista) foi lido por inteiro, validado (`validate_package.py` e os 42 testes sintéticos do `starter/` passam, só para os materiais demonstrativos) e copiado como referência em `docs/addenda/v2.5/package/`. `docs/addenda/v2.5/GAP_ANALYSIS.md` mapeia cada requisito aos caminhos reais do repositório (descoberta: `olt.autofind` já está no catálogo, sem parser nem tela; inventário de profiles: não existe; jobs, capacidades, ERP hub e o padrão de prévia do ADR-0036: reusados). `ADR-0040` decide a ordem: v2.5 somente leitura **à frente do FC22-014**, cuja lacuna de dry-run/diff ele **vai** cobrir para provisionamento (planejado; segue aberta até implementar e aceitar; o catálogo genérico de workflows também continua aberto); escrita só após homologação em LAB e emenda do ADR-0030. Backlog (`ROADMAP_BACKLOG.md`) conciliado. Nenhum código, nenhuma flag ligada, nenhum acesso à OLT.

## Unreleased — uma escrita por vez por dispositivo no despacho de jobs (FC22-015, 2026-11-02)
- API: `GET /v1/edge/jobs/next` não despacha um job de **escrita** (`OPERATIONS[...].writes`) enquanto outro job de escrita no **mesmo alvo** está em curso (`DISPATCHED`, `ACCEPTED`, `DEVICE_PENDING`, `VERIFYING`). O job fica `APPROVED` e espera (nunca é cancelado; o TTL continua valendo); leituras (`refresh`, `collect`, `olt_query`) não esperam nem seguram escritas; alvos diferentes não se afetam. A checagem entra na própria seleção (sem bloquear a fila atrás de um job parado) e é refeita sob `pg_advisory_xact_lock` do alvo, para duas chamadas simultâneas não verem o alvo livre. Nenhuma migração. Um job de escrita **de bancada** que o Edge aceitou e depois calou (`ACCEPTED`/`DEVICE_PENDING`/`VERIFYING`) é, passados 30 min sem se mover (`STALE_AFTER`), reconciliado para `UNKNOWN` (terminal; relato tardio recusado com 409) e o alvo fica **travado para escrita** como qualquer escrita de bancada que terminou `UNKNOWN` (ADR-0030 item 6): só uma pessoa libera, com `bench-unlock`; o relógio nunca libera o alvo. Qualquer outra escrita (nenhuma está homologada hoje) **não é liberada por tempo**: continua segurando o alvo (falha fechada). Testes novos: ordem/leitura/alvos diferentes; escrita genérica parada que segura o alvo para sempre; escrita de bancada parada que vira `UNKNOWN` e trava o alvo; e **duas chamadas simultâneas** de `next` com barreira (12 rodadas: exatamente um envelope; sem o lock, o teste falha com `[200, 200]`, provado). 921 passed. Não muda o gate: `HOMOLOGATED_WRITES` segue vazio e as escritas de bancada seguem com as travas do ADR-0030.

## Unreleased — R-D004 no diagnóstico guiado (2026-11-02)
- Web: o diagnóstico guiado ganha o **passo 6, Sessão do roteador com o ACS (R-D004)**. Só compara OLT e ACS com roteador **confirmado**; ONU online e roteador sem Inform recente é **Hipótese** (nunca "sem internet"; entra na Conclusão quando o passo 4 não é hipótese); sem roteador confirmado, execução velha (> 15 min), de outra ONU ou fora do formato esperado: **Indisponível**, nada é afirmado. O achado é lido em formato fechado (`readRd004`). As execuções dos passos 4 e 6 ficam juntas (`run` e `run4`); a rota do BFF aceita só `rule=R-D001|R-D004` e `keep=<uuid>`. O seed passa a dar ao CPE DEMOA0001 um Inform de 3 h atrás e ao DEMOA0002 um de 2 min atrás. E2E funcional: 33 passed (novo teste do passo 6). A R-D003 (Edge sem sinal) não entrou: a ONU do cliente não carrega o Edge, e a leitura é por Edge, não por assinante.

## Unreleased — API e Edge da LAB reimplantados com a R-D004 (2026-11-02)
- Ops (ordem do responsável): backup lógico da LAB (detalhes só no host) e depois API/relay/consumer em `fdf4da8` com a migração 0039 (head 0039; `last_inform_at` e `last_inform_observed_at` nulos até o Edge enviar). Edge do host do ACS trocado para `0.1.0-lab-fdf4da8` depois do fim de uma coleta da OLT (guard de ritmo), config inalterada, cópia anterior do binário no host. Evidência redigida em `docs/operations/DEPLOY_LAB_2026-11-02_API_EDGE_R-D004.md`. Conferido: 9 de 9 CPEs com `last_inform_at` reportado nos últimos 10 min; R-D004 sobre as 2 ONTs de bancada confirmadas = "observado: o CPE informou recentemente" (avaliação só leitura, sem serial impresso).

## Unreleased — status e roadmap atualizados contra o código (2026-11-02)
- Docs: `IMPLEMENTATION_STATUS.md` ganhou a seção "Estado atual" (o resto virou histórico) e `ROADMAP_BACKLOG.md` teve as linhas desatualizadas corrigidas (W9, FC22-003/005/006/009, FC24-02, QI-02) e uma seção de 2026-11-02 que separa o que depende de bancada, de decisão, de construção e de dado que ninguém coleta. Cada correção veio de leitura do código ou dos arquivos versionados; o que não foi verificado está dito como tal.

## Unreleased — capturas da ajuda regeneradas (2026-11-02)
- Docs: as capturas (desktop e mobile) de 10 artigos foram regeneradas do sistema funcionando (seed sintético, nenhum dado real) para refletir o verde `--ok` novo, a régua compacta na lista da Rede, a ONU 360° sem os cartões de banda e qualidade e a aba Histórico. `last_verified` desses artigos = 2026-11-02. `tests/validate_help.py`: PASS. Os artigos ainda em rascunho continuam em rascunho.

## Unreleased — teste de UI do ping e correção do BFF que impedia a tela de carregar (2026-11-02)
- **Correção (bug real):** o BFF `/bff/cpes/{id}/ping` devolvia as capacidades já tratadas, e `PingTestSection` as tratava de novo esperando o formato bruto da API: a leitura voltava `null` e a aba **Ping e latência** do Diagnóstico mostrava sempre "Não foi possível carregar o teste de ping". Achado pelo primeiro e2e de UI do ping (o estado REAL). Agora o BFF valida e envia `caps` no formato bruto da API mas por LISTA FECHADA de campos (nada de `cpe_id`, `job_id`, `edge_support`, certificação), e a lista `runs` já tratada; o teste real confere as chaves do corpo. A LAB ainda roda o web anterior: precisa de novo deploy do web.
- Testes: `e2e/ping.spec.ts` (6): estado REAL indisponível no aparelho demo (com axe), pedido que envia só `{key, target_id}`, resultado com traço no lugar de número ausente, 502 ambíguo com **Confirmar pedido** repetindo a MESMA chave e o MESMO destino, trava que só sai quando uma leitura mostra ESSA execução (nunca pelo relógio, nunca pela execução de outra pessoa), recusa 409 sem trava. O seed do e2e passa a ligar `quality_active_tests` no provedor demo (só a tela; o aparelho demo segue sem homologação). Inspetor completo: 55 passed, 2 skipped (os de flag desligada).

## Unreleased — aba Histórico na Visão 360 do assinante (2026-11-02)
- Web: `/assinantes/[id]` ganha a aba **Histórico** (30 dias de mudanças de estado da ONU, o mesmo componente, a mesma rota e a mesma flag `onu_quick_inspector` do painel da Rede). Só existe com ONU aprovada e a flag ligada; o Wi-Fi continua sem aba (sem fonte homologada). Nenhuma rota nova. E2E funcional: 32 passed (o teste da Visão 360 abre a aba, confere as quedas e a primeira observação, e passa pelo axe nela). Recuo provado (`ASSINANTE_HISTORICO_FLAG_OFF=1`, spec `assinante-historico-flag`): com `onu_quick_inspector` desligada a aba não existe, `?aba=historico` cai na Conexão e nenhum pedido de histórico sai; com a flag ligada o mesmo teste falha (controle negativo).

## Unreleased — regras R-D003 e R-D004 do motor de diagnóstico (2026-11-02)
- API: `R-D003 v1` (Edge sem sinal: o coletor parou, então os dados de ONU dele são velhos e não provam queda; escopo `edge_id`) e `R-D004 v1` (ONU online na OLT e CPE sem Inform recente: aponta a sessão com o ACS, nunca "assinante sem internet"; escopo `cpe_id` ou `onu_id` com vínculo confirmado). Funções puras, sem relógio: o veredito de silêncio e de frescor é gravado nas entradas, então a repetição é reproduzível. Sem dado, ONU sem vínculo confirmado, leitura velha ou ONU que não está online: nada é afirmado. Só leitura: não abre incidente nem publica evento. Nenhuma migração. O R-D004 usa `cpes.last_inform_at`, o `_lastInform` do PRÓPRIO ACS (migração 0039, colunas novas `last_inform_at` e `last_inform_observed_at` = quando o Edge o REPORTOU; só avança; um snapshot que omite o campo não renova a atualidade; NULL até o Edge enviar). Não usa `observed_at`: esse é a hora da coleta do Edge, e um coletor parado não pode parecer um CPE parado (achado do Codex r1). Sem a coluna preenchida, a regra diz "desconhecido".
- Edge: o snapshot de CPE passa a levar `last_inform_at` (do `_lastInform` do ACS; omitido se vazio, ilegível ou no futuro). **O Edge da LAB ainda não foi reimplantado**: até lá o R-D004 responde "desconhecido" para todo CPE.
- `POST /v1/diagnostics/runs` aceita `edge_id`; as entradas guardadas da R-D002 ganham `inform_age_seconds` e `inform_fresh` (ignorados por ela). Testes: 916 passed (7 novos: regras puras, propriedade, execução pela API, escopos, isolamento por tenant).

## Unreleased — rotação do cwmp.auth concluída nas ONTs de bancada (2026-11-02)
- Ops: fases 2 e 3 da rotação do `cwmp.auth` do ACS. O par novo foi configurado na Huawei EG8145V5 e na ZTE F670L pelo responsável; `cwmp.auth` ficou só com o par novo; o par antigo exato passou a dar 401 e as duas ONTs seguem informando (0 falhas). Nada no código. Lição registrada em `docs/operations/GENIEACS_CWMP_AUTH_ROTATION.md`: gravação direta no Mongo só vale depois do snapshot de até 300 s do GenieACS.

## Unreleased — ONU 360° sem os cartões de teste de banda e de qualidade (2026-11-01)
- Web: a ONU 360° deixa de ter os cartões **Teste de banda** e **Qualidade do serviço**. Os dois continuam nas abas do painel da Rede e também na página de Diagnóstico (abas Velocidade e Qualidade), que a 360° já liga pelo botão **Diagnóstico**; só não há mais cartão na 360°. Nada mudou nos componentes, nas flags nem no BFF.
- Testes: os dois testes que esperavam o cartão passam a provar que ele não existe na 360° e que o conteúdo está no Diagnóstico; os testes de flag desligada (`SPEED_FLAG_OFF`, `QUALITY_FLAG_OFF`) agora também abrem o Diagnóstico e provam que ele mostra só o aviso de indisponível. Docs (ajuda de banda e de qualidade, ADR-0038 e ADR-0039) ajustadas.

## Unreleased — base do e2e verde e contraste da régua (2026-11-01)
- E2E: as 5 falhas que já existiam na base foram resolvidas. Causas reais: (1) `/dispositivos/capacidades` tinha uma região rolável sem foco de teclado (axe `scrollable-region-focusable`, claro e escuro): agora `tabIndex=0`, `role="region"` e nome acessível; (2) o teste de refresh de sessão procurava um título "Rede" que a UX nova não tem (o `h1` é o nome da OLT): a sessão já renovava, o teste foi corrigido; (3) três testes do painel/abas assumiam que a `DEMOA0001` não tem roteador vinculado, mas o `app.spec` (projeto `funcional`, que roda antes) a vincula: passaram a usar a `DEMOA0003`. Bateria completa: 17 puros, 32 funcionais, 48 do inspetor, 0 falhas.
- Contraste (WCAG) medido nos dois temas: no tema claro o `--ok` (#1B7F4B) ficava em 4,36–4,43:1 como texto sobre linha selecionada/hover (precisa 4,5:1) e o marcador da faixa "bom" em 2,92:1 (precisa 3:1). Agora `--ok` claro = #197645 (≥ 4,9:1 em todas as superfícies, inclusive os fundos suaves) e as faixas da régua usam 30 % de intensidade (`BAND_TINT`; marcador ≥ 3,3:1). Tema escuro já passava. Guarda em `e2e/optics-contrast.spec.ts` (lê os tokens de `globals.css`; com o verde antigo o teste falha).
- O marcador compacto da régua ganhou um anel da cor da superfície (o contraste dele não depende da faixa, inclusive nas transições do gradiente). O guarda de contraste acha os temas pelo seletor, exige todos os tokens, mede texto (4,5:1), fundo/borda (3:1) e marcador, e um teste no Chromium prova que o `color-mix(in srgb)` real é a composição usada. Codex: 3 rodadas, approve na r3.
- Não regenerei as capturas da ajuda (`docs/help/assets`): as cores mudaram um pouco.

## Unreleased — UX do Diagnóstico a partir do protótipo do Lovable (2026-11-01)
- Web: a lista da Rede (`OnuWorkspace`) mostra a régua óptica compacta (`dense`: símbolo + só a faixa, rótulo completo no `title`/`aria-label`) ao lado do número do Rx; a coluna "Dado" pode quebrar linha para a lista caber ao lado do painel.
- Web: na régua grande e na média o valor numérico sobe junto com o marcador (encostado na borda nas pontas do eixo); o rótulo da faixa fica acima.
- Web: cada indicador da Qualidade ganhou "Fonte · idade" (`indicatorSource`: só as métricas que o indicador cita e que têm leitura; com mais de uma, a idade é a da MAIS ANTIGA; sem leitura: "Fonte: sem leitura"). Rodapé fixo: "Sem contato com o ACS não significa ONU offline. Uma sessão WAN não prova qualidade da internet ou do Wi‑Fi."
- Critério único `hasReading` (status valid/stale E valor que não seja null, vazio ou só espaços; 0 e false contam): vale para o valor mostrado, a fonte/idade, o estado nos detalhes e o cartão do indicador ("ok" sem leitura citada = "Sem leitura"). A régua compacta da lista leva a ressalva das faixas não homologadas (aria-label, title e nota visível). Codex: 7 rodadas, approve na r7.
- Decisão: NÃO adotado o rótulo "Confirmado/Hipótese/Indisponível" do protótipo por indicador: a plataforma não julga o sinal ("Sem anomalia observada" não é "Confirmado"), então a confiança continua só nas hipóteses.
- Testes: `quality-source.spec.ts` (puros), régua média (valor sobre o marcador), lista da Rede (régua + número em cada linha), fonte e frase de cautela na Qualidade. Bateria completa: as mesmas 5 falhas que já existiam na base, nenhuma nova.

## Unreleased — trava de pedido do teste de banda e aceite do ping da ZTE (2026-11-01)
- Web: `SpeedTestSection` passa a usar o mesmo protocolo de trava do ping: marcador `{runId, chave, pedido}` gravado ANTES do POST (sem armazenamento, o pedido não sai); só a execução DESTE pedido destrava (lista ou confirmação pelo id); pedido incerto nunca se resolve por tempo e "Confirmar pedido" repete a MESMA chave e o MESMO corpo (inclui `group_id`); `runId` ilegível vira pedido incerto sem apagar a trava. BFF `speed/runs` devolve `run_id`; BFF de leitura (speed e ping) aceita `?run=` e devolve `run_seen`. Codex: 4 rodadas, approve na r4. E2E do speed: 18 passed, 1 skipped.
- Seed do e2e: `set_wifi_ssid` é operação de bancada e exige o parâmetro `ssid` (a prévia do seed era recusada com 422).
- `ping_test` da ZTE F670L `V9.0.11P1N10B` promovido a `observed` com o aceite do responsável (2026-11-01), evidência de UMA execução confiável (5 de 5, 11/12/12 ms). Huawei EG8145V5 NÃO aceita (1 de 5 sem causa conhecida): segue `identified`.
- Lovable aplicou o plano aprovado do protótipo de Diagnóstico (projeto próprio do Lovable, dados sintéticos, commit `c4e39d8`); nada foi importado para este repositório ainda e o contraste WCAG não foi medido.

## Unreleased — Diagnóstico da ONU e régua de sinal óptico (2026-11-01)
- Web: página `/rede/onu/{id}/diagnostico` (flag `onu_quick_inspector`) com abas por link (Resumo, Velocidade, Qualidade, Latência e DNS), reaproveitando `SpeedTestSection`/`QualitySection` e a nova `PingTestSection`; cada teste só aparece com roteador vinculado e a flag própria ligada, e o Resumo diz em texto por que um teste está indisponível. Botão "Diagnóstico" na ONU 360° e no painel lateral da ONU.
- Web: `OpticalRuler` (três tamanhos) no lugar do número solto do Rx, com faixas de REFERÊNCIA G.984.2 classe B+ (−28/−25/−10/−8 dBm) em `src/lib/optics.ts`, texto e símbolo sempre, aviso "não homologada", e dado defasado/ausente nunca classificado. ADR-0037 ganhou a emenda que permite isso só na apresentação (a API segue sem julgar o Rx).
- Web: BFF `/bff/cpes/{id}/ping` e `/ping/runs` (formato fechado, só id lógico do destino). Jitter e DNS aparecem como "ainda não disponível" com o motivo (o aparelho só informa mín/méd/máx; os modelos de bancada não expõem NSLookup).
- Testes puros da régua em `apps/web/e2e/optics.spec.ts` (projeto `puros`). Os e2e de página não rodaram: a stack efêmera não tem o seed demo com vínculo ONU↔CPE.

## Unreleased — ping_test na nuvem (2026-11-01)
- API: `ping_test` entra no catálogo de bancada (ADR-0030 emenda, linha Q1) com UM parâmetro, o id lógico do destino. Endpoints por CPE `GET /v1/cpes/{id}/ping/capabilities`, `GET|POST /v1/cpes/{id}/ping/runs`, `GET .../runs/{run}`; tudo responde 403 `feature_disabled` com a flag `quality_active_tests` desligada. Pedido pelo caminho genérico de jobs é recusado (`use_ping_api`).
- Permissão nova `diagnostics:ping_run` (R2, MFA recente), mesmos papéis do teste de banda. `ping_test` é autorizável pela API só por `engineer` e `isp_admin`.
- Migração 0038: `probe_targets` (catálogo de destinos lógicos, dono único = um Edge, sem coluna de endereço, só o CLI do dono escreve) e `ping_test_runs` (uma linha por teste, número só com medição). CLI `probe-target-set` e `bench-authorize --ping-target`.
- Reserva compartilhada por CPE: um diagnóstico por vez, de qualquer tipo (o teste de banda passa a recusar com `cpe_busy` quando há ping vivo), e no máximo 6 pings por hora por CPE (`rate_limited`).
- O resultado vem do relatório fechado do Edge: perda calculada das contagens (5 envios fixos), tempos só com ao menos uma resposta, amplitude = máx − mín (não é jitter). Relatório fora do formato = job `FAILED` `invalid_result` e alvo travado, como no teste de banda.
- Contrato `contracts/job-envelope.schema.json` ganha a variante `{target}` para `ping_test`. Sem DNS (nenhum modelo de bancada expõe `NSLookupDiagnostics`).
- Ordem de implantação: Edge primeiro (com a seção `ping` na configuração), depois a nuvem; ver `docs/addenda/v2.2-qos/EDGE_PING_CONFIG.md`. A capacidade `ping_test` de cada modelo nasce `identified` (nenhuma execução real ainda).

## Unreleased — ping_test no Edge (2026-11-01)
- Edge: `ping_test` (TR-143 IPPing) na bancada, ADR-0030 emenda (linha Q1): catálogo local de destinos (`ping.targets`, IP literal, mesmas regras do speed), forma fixa (5 repetições, 1000 ms), pela WAN de serviço verificada conectada antes da única escrita, relatório fechado (`success`, `failure`, `avg_ms`, `min_ms`, `max_ms`). Pacote `internal/ping`, `nbi/ping.go`, despacho no `bench`, verificação de envelope em `jobs`. `speed.ParseDestination`/`ParseCoreCIDRs` exportados e `postSetValues`/`diagCacheLeaves`/`checkServiceWAN` extraídos do speed sem mudar o comportamento. Testes: `go test ./...` verde.
- Medido nos dois aparelhos de bancada: ambos expõem `IPPingDiagnostics`; NENHUM expõe `NSLookupDiagnostics`; sem jitter (só mín/méd/máx). Ver `docs/addenda/v2.2-qos/EDGE_PING_CONFIG.md`.

## Unreleased — Speed na WAN de serviço, com fidelidade (2026-11-01)
- Edge: antes da única escrita do teste de banda, lê o estado da WAN de serviço configurada (`ConnectionStatus`/`Status`) e recusa com `wan_not_connected` se não estiver conectada, ausente ou ilegível. Testes `go test ./internal/nbi ./internal/bench`.
- Edge: horário de dispositivo com relógio sem sincronismo (1970) passa a valer (só a diferença BOM→EOM é usada); o ADR-0038 só descarta o ano 1.
- ZTE F670L: 3xx observado (segue), aceite de risco registrado, download 10 MB (parcial) e 200 MB (completo, 257,86 Mbps em 6,2 s) pela WAN PPPoE da ZTE. Evidência em `docs/wiki/bench/`.
- Docs: `docs/operations/SPEED_HOMOLOGACAO.md` seção 7 (o que o teste mede e seus limites).

## Unreleased — encerramento de contas de homologação (2026-11-01)
- CLI do dono `deactivate-account`: desativa contas de serviço por nome exato e encerra o vínculo de usuários num tenant (recusa contas `edge_agent`, usuários `isp_admin`, usuários que pertencem a outro tenant e usuários com delegação viva no tenant); um evento `account.deactivated` por conta, sem e-mail no payload. Testes em `apps/api/tests/test_owner_deactivate.py`.

## [0.0.0-spec] - 2026-10-27

- PRD e arquitetura dual TR-069/TR-369.
- Kit inicial com inventário de módulos, catálogo seed, contratos, orquestração e comandos de desenvolvimento.
- Nenhuma integração real com dispositivos habilitada.

## Unreleased — Sprint 0 PR 1
- Kit v2 importado; starter movido para `apps/api`.
- Migração 0001: tenants, users_global, tenant_memberships, service_accounts, audit_log, events_outbox + RLS forçada + role `fibercore_app`.
- Auth JWT/Argon2id, RBAC, `X-Workspace-ID`, service accounts, CLI de provisionamento.
- Registry de módulos com probes reais; Compose com `migrate` one-shot.

## Unreleased — Sprint 1 PR 5
- Migration 0005 (olts, pon_ports, onus, cpes, bindings; RLS; sem DELETE para runtime).
- Ingestão `POST /v1/edge/{olt,cpe}-snapshots` (token ligado a um edge; anti-hijack; fora de ordem ignorado; `certified` só no servidor) e leituras `/v1/{olts,onus,cpes}` com `freshness`.
- OpenAPI 0.3.0-draft: schemas Olt/Onu/Cpe reescritos para o implementado (breaking vs 0.2 draft; sem consumidores ainda).

## Unreleased — Sprint 2 PR 8
- Migration 0006: customers (documento só como HMAC+last4), associations (1 aprovada por ONU), import_batches.
- `POST /v1/erp/import-csv`, `/v1/customers`, `/v1/associations` (+approve/reject, auditados, evento no outbox). OpenAPI 0.4.0-draft.

## Unreleased — Sprint 2 PR 9
- Migration 0007 `incidents`; correlação de queda em massa por PON na ingestão (histerese, dedupe, evidência só com contagens); `/v1/incidents`, `/v1/incidents/{id}/ack`; eventos `incident.opened/resolved`. OpenAPI 0.5.0-draft.

## Unreleased — Sprint 3 PR 10
- Migration 0008 (jobs, job_approvals); `/v1/jobs/*`, `/v1/edge/jobs/next|result`; assinatura Ed25519; Edge verifica assinatura/binding/expiração/nonce e só executa collect/refresh. OpenAPI 0.6.0-draft.

## Unreleased — Adendo v2.1 (PR 11)
- Kit v2.1 (design system, help center contract, Caddy example, validate_help) importado; OpenAPI 0.7.0-draft (`/api/v1`); profile Compose `public` com Caddy; `scripts/test-proxy.sh`; lockfile corrigido (cryptography) e atualizado para versão sem advisories; CI valida import da imagem.

## Unreleased — Hardening 13
- Migration 0010 `login_attempts`; lockout 5 falhas/15 min em `/v1/auth/token` e `/v1/auth/service-token` (429 + Retry-After); BFF mostra mensagem específica.

## Unreleased — Correlação por quedas recentes (ADR-0018)
- Migration 0012 (`onus.last_online_at/down_since`, `incident_onus`); `pon_mass_outage` passa a medir ONUs que CAÍRAM na janela de 6 h (só em snapshot fresco pelo relógio do servidor) (crônicas fora do cálculo), incidente guarda as ONUs que cobre e resolve quando elas voltam. Motivo: 37% das ONTs de uma OLT real estavam offline crônicas e a regra antiga abriria incidente falso permanente em 2/32 PONs.

## Unreleased — Segurança da conta / MFA (PR 27)
- Tela `/conta/seguranca` (ativar/desativar MFA, QR, códigos de recuperação mostrados uma vez) e política `MFA_REQUIRED_ROLES` (403 `mfa_enrolment_required`, sem auto-downgrade, boot falha com papel desconhecido). ADR-0017 (adendo).
- Correção: `tenant_conn` confirma a transação ANTES de enviar a resposta (`scope="function"`; fastapi >= 0.121) — corrigia um `job not found` intermitente logo após o preview.
- Correção: ativação do MFA serializada (`FOR UPDATE`) e enroll com upsert condicional (não sobrescreve MFA ativo); 409 para quem perde a corrida. Codex: 4 rodadas, approve final (pareceres em `docs/wiki/reviews/raw/27-*`).

## Unreleased — ONU 360 (PR 28)
- `GET /v1/onus/{id}` (estado, OLT/PON com idade do dado, incidente com `incidents:read`) e `GET /v1/onus/{id}/customer` (dado pessoal: `customers:read`, auditado). Página `/rede/onu/[id]`, painel lateral `EntityDetailDrawer` (dialog) na tabela de Rede, how-to com capturas. Codex: 4 rodadas, approve.

## Unreleased — Edge × GenieACS NBI (PR 30)
- Coletor GenieACS descarta identidades provisórias `DISCOVERYSERVICE` (37 de 43 dispositivos no servidor real) e reporta só contagens (`no_serial`, `placeholder_identity`). Teste com fixture sintética da estrutura real; mutação verificada.
- Identidade de CPE como REIVINDICAÇÃO do dispositivo: serial canônico (trim + maiúsculas) no Edge e na API, migration 0013 (CHECK de forma canônica + único `(tenant, cpe, connector, protocol)`; recusa dados colidentes com diagnóstico), ingestão que IGNORA e conta (`conflicts`) reivindicações conflitantes sem derrubar o lote, travas advisory em ordem por chave de serial e de binding. Contrato OpenAPI (`CpeSnapshotAck`). Codex: 11 rodadas, approve (4 alegações contestadas com medição/teste; pareceres em `docs/wiki/reviews/raw/30-*`).

## Unreleased — Redefinição de MFA por administrador (PR 31)
- `GET /v1/members` e `POST /v1/members/{id}/mfa/reset` (senha + segundo fator do administrador, guarda de conta multi-workspace, auditoria, sessões revogadas, fail closed). Tela Administração › Membros com abas, how-to com captura, E2E do fluxo completo. ADR-0017 (adendo).
- Migration 0014 `users_global.tokens_valid_after`: revogação verificável de access tokens já emitidos (reset de MFA encerra sessões na hora); `iat` do JWT passa a ser fracionário.

## Unreleased — Backup agendado
- `scripts/backup-scheduled.sh` (cron diário 03:15) reaproveita `backup.sh`/`restore-verify.sh` (agora com `COMPOSE_PROJECT` p/ a stack `fibercore-prod`), verifica cada dump restaurando num banco descartável e mantém os 14 mais recentes.

## Unreleased — Regeneração de códigos de recuperação (PR 33)
- `POST /v1/auth/mfa/recovery-codes` (senha + segundo fator; troca o conjunto inteiro na mesma transação, serializado com disable/reset) e botão em Conta › Segurança da conta. How-to e contrato atualizados.

## Unreleased — Adendo v2.2 (PR 34, somente planejamento)
- Pacote do adendo copiado para `docs/addenda/v2.2/` sem alterar nada existente; `GAP_ANALYSIS.md` (matriz de gaps + 18 conflitos + plano), `RECONCILED_API.md` + OpenAPI reconciliado, `SCREEN_COMPONENT_MAP.md`, `TEST_DESIGN.md`; ADR-0019…0023; backlog FC22 integrado ao `ROADMAP_BACKLOG.md`; `tests/validate_addendum_v22.py` (no `make validate`). **Nenhuma funcionalidade v2.2 foi implementada neste PR.**

## Unreleased — Capability Registry, fatia mínima (PR 35, FC22-002)
- Migration 0015 `device_capabilities` (por tenant, RLS forçada, CHECKs; `observed/certified` exigem evidência+data; app só lê), `GET /cpes/{cpeId}/capabilities` (documentada no contrato sem handler) e `GET /olts/{oltId}/capabilities`, catálogo = operações reais do motor de jobs, CLI `capability-set` (evidência obrigatória, evento `device.capabilities.changed`), bloco "Capacidades" no card Ações da ONU 360 + how-to e capturas. Registro vazio ⇒ tudo `Desconhecida/Identificado`; o registro NUNCA libera escrita (o gate é o do motor de jobs).
- **Não feito (declarado)**: flag por tenant (DoD parcial), gate de jobs ligado ao registro, Edge alimentando o registro, capacidades TR-369/Wi-Fi.

## Unreleased — Flags por tenant + envelope de proveniência (PR 36, FC22-003/ADR-0023)
- Migration 0016 `tenant_features`; `app/core/features.py` (catálogo+padrões no código); `GET /v1/tenant/features`; CLI `feature-set`; `403 feature_disabled` (kill switch do registro de capacidades). ONU 360: `provenance{state,olt,pon}` + `SourceChip`. ADR-0020/0021/0023 → Accepted (0021 aprovado pelo responsável em 2026-10-29).

## Unreleased — Vínculo ONU↔CPE por evidência + Customer Context (PR 37, FC22-004/ADR-0021)
- Migration 0017 `onu_cpe_links` (RLS forçada; `suggested|confirmed|rejected`, confiança, evidência; `CHECK` sugestão ⇒ sem revisor; índices únicos parciais: um confirmado por ONU e por CPE; app só `INSERT` + `UPDATE(status, reviewed_by, reviewed_at)`).
- `POST /v1/onu-cpe-links/suggest` (serial igual ⇒ sugestão 0.50, 0.20 se ambíguo; idempotente; nunca confirma), `GET /v1/onu-cpe-links`, `POST …/{id}/confirm|reject` (pessoa; auditado + outbox; 409 em ambíguo/já revisado/duplicado). `GET /v1/customers/{id}/context` (read-only, `customers:read`, auditado, flag `customer_context`): só ONUs de associação aprovada, CPE só com vínculo confirmado, proveniência por bloco, status `unknown > stale > partial > complete`, incidente só com `incidents:read`.
- ONU 360: bloco `cpe` + card "Roteador (CPE)" com confirmar/rejeitar (BFF `/bff/onu-cpe-links`). Seed demo liga as flags no tenant demo. Flags continuam **desligadas por padrão** em produção.
- TTL do dado de ERP = 7 dias (`ERP_FRESH_FOR`), **aprovado pelo responsável em 2026-10-29**; acima disso o contexto vira `stale`.
- **Não feito (declarado):** busca por cliente/contrato na UI (FC22-005), regras de vínculo além de `serial_equal`, desfazer um vínculo confirmado.

## Unreleased — Visão 360 do assinante (PR 38, FC22-005)
- `/assinantes/[id]` (Next, servidor): estado geral explicado (Completo/Parcial/Defasado/Desconhecido), seletor de ONU, abas por query (`?aba=`) só com dado — Conexão (conexão + roteador + incidente), Óptica, Roteador (CPE), Cliente, Ações (sempre bloqueadas). Lista "Clientes · visão 360" em Assinantes. Tudo atrás das flags `subscriber_360` **e** `customer_context` (desligadas por padrão; faltando qualquer uma a rota é 404 e a lista não aparece; o bloco do roteador precisa ainda de `onu_cpe_links`). Consome `GET /v1/customers/{id}/context` (sem API nova).
- Referência visual do Lovable (um lote); how-to `assinantes/visao-360` + capturas reais 1440×900/390×844; seed demo liga a flag.
- **Não feito (declarado):** busca por cliente/contrato no ⌘K, Wi-Fi e Histórico (sem fonte homologada), caminho "flag desligada" não coberto por E2E (só 404 por construção + flags testadas no backend).
## Unreleased — Motor de regras de diagnóstico, R-D001 v1 (PR 39, FC22-006/ADR-0024)
- `app/core/diagnostics.py`: regra pura e versionada; R-D001 v1 extraída do correlator **sem mudar comportamento** (o `noc.py` a chama para decidir abrir; teste de propriedade com 2000 casos contra a fórmula original). Migration 0018 `diagnostic_runs` (append-only, RLS forçada). `GET /diagnostics/rules`, `POST /diagnostics/runs` (somente leitura, não abre incidente), `GET /diagnostics/runs/{id}` com `reproducible`. Flag `diagnostic_engine` (desligada por padrão), permissão `diagnostics:run`.
- **Não feito (declarado):** R-D002..004 (sem dados de Wi-Fi/WAN/sessão ACS), UI de troubleshooting guiado (FC22-007), completude de PON persistida.
## Unreleased — Diagnóstico guiado (PR 40, FC22-007)
- `/assinantes/diagnostico/[id]` (Next, servidor): 5 passos (cliente, ONU, estado/óptica, padrão R-D001, roteador) com rótulo Confirmado/Hipótese/Indisponível, painel de evidências com fonte/idade, ação de leitura por passo, conclusão que só existe depois de executar, "Gerar resumo para ticket" sem alterar a rede. BFF `/bff/diagnostics/run/[customer]/[onu]` executa a regra (somente leitura) e volta com o resultado; a execução só vale para a ONU da tela. Atalho "Diagnóstico guiado" na Visão 360. Exige as flags `subscriber_360`, `customer_context` e `diagnostic_engine` (fora: 404).
- API: `POST /v1/diagnostics/runs` aceita `onu_id` (PON resolvida no servidor; exclusivo com `olt_id`/`pon_id`).
- **Não feito (declarado):** R-D002..004 (sem dados), conclusão com Wi-Fi/WAN, histórico/timeline (FC22-007 pede EvidenceTimeline: sem fonte homologada).
## Unreleased — NOC Command Center (PR 42, FC22-009)
- API: `GET /v1/incidents` ganhou `impact` por incidente (clientes distintos via associações APROVADAS; sem `customers:read` = `hidden`, nunca 0; sem membros = desconhecido), `summary` (4 números sobre TODOS os abertos; clientes afetados não inclui Edge silencioso) e `order=priority` (ordem documentada, sem score; o padrão `recent` não mudou); `GET /v1/incidents/{id}` para o painel (evidências, impacto, até 50 ONUs-membro, sem nomes de clientes).
- UI `/noc`: 4 KPIs, filtro "só não reconhecidos", fila na ordem do servidor, impacto com fonte, incidente em painel lateral (foco/Esc) via BFF `GET /bff/incidents/[id]`. How-to atualizado, capturas reais.
- **Não feito (declarado):** reconhecer incidente pela UI (ack existe na API), correlação com dados de Edge além do silêncio, R-D003 como regra.

## Unreleased — PR 43 (Edge → OLT, ritmo seguro)
- Edge: a coleta de OLT (SSH/CLI e SNMP) passa por UM guard por equipamento físico: uma coleta por vez, intervalo mínimo (`collect_seconds`, padrão 15 min no CLI), resfriamento após falha (`cooldown_seconds`, padrão 15 min CLI / 5 min SNMP).
- O estado do guard (última tentativa + resfriamento) é gravado em `olt-guard.json` (0600, atômico) ANTES de qualquer E/S e sobrevive a restart; falha ao gravar = não toca na OLT; arquivo corrompido (inclusive `null`) = assume que a OLT acabou de ser tocada; timestamps >24 h à frente são normalizados e persistidos.
- Instância única por diretório de estado (`edge.lock`, flock). Chave do guard = host físico (`config.DeviceKey`), independente de transporte/porta; a config recusa duas entradas para o mesmo equipamento e exige IP literal no endereço de OLT por CLI.

## Unreleased — PR 44 (Edge → OLT, observabilidade)
- Edge: cada tentativa que chega à OLT registra `olt collected`/`olt collection failed` com duração (nunca saída do equipamento); o orçamento de tempo vira proporcional às PONs (1 min + 15 s/PON, entre 5 e 9 min) e cobre também o login.

## Unreleased — PR 45 (itens pequenos do v2.2)
- NOC: **Reconhecer incidente** no painel lateral (BFF `POST /bff/incidents/{id}/ack`; só registra a ciência, auditada; 403/409 tratados).
- Busca global (⌘K): clientes por nome a partir de 3 letras (BFF `GET /bff/search/customers`, só id e nome; a API audita o acesso).

## Unreleased — PR 46 (SD-001 gate B0, só documentação)
- `docs/feature-packs/SD-001/`: relatório de compatibilidade com a base v2.2, README do pacote; ADR-0025 (Proposed); ligação ao backlog sem renumerar. Nenhum código, contrato, migração ou versão alterado.

## Unreleased — PR 47 (SD-PR-01: contratos e mocks do SD-001, flags desligadas)
- ADR-0025 aceito pelo Tech Lead (2026-10-29). `contracts/sd001/`: schemas de evidência e de saída consultiva do copiloto, sobreposição OpenAPI **proposta** (`diagnostic_jobs`, propostas, aprovação, execução) e eventos no formato do outbox; fixtures sintéticas em `tests/fixtures/sd001/`.
- Flags por provedor `smart_diagnostics_jobs|active_tests|remediation|copilot`, todas desligadas (`features.py`). Nenhum endpoint, migração, tabela, evento emitido ou mudança no contrato canônico; `/devices/{id}/capabilities` do pacote não foi criado (já existe `/cpes/{id}/capabilities`).

## Unreleased — PR 48 (SD-PR-02: leitor passivo de parâmetros do CPE, ADR-SD-002)
- Edge: `nbi.CachedParams` lê, por GET, folhas exatas de uma lista fechada (WAN/enlace, uptime, rádio Wi-Fi habilitado/canal) do que o GenieACS já tem em cache, com validação de tipo e descarte do que não é esperado. Não é usado pelo coletor: nada novo vai à nuvem, sem endpoint nem migração.
- ADR-SD-002 (Proposed): evidência da LAB mostra que o cache só tem dados do Inform (sem WAN/Wi-Fi); a leitura ativa (`getParameterValues`) ficou separada e depende de autorização explícita. Estados novos no contrato de evidência.

## Unreleased — PR 49 (catálogo de consultas somente leitura da OLT, ADR-0026)
- Edge: `olt.Queries`/`HuaweiR015.RunQuery` — 25 consultas `display` tipadas (global, slot, PON, ONU), parâmetros inteiros limitados, renderização no Edge, padrão estrito e proibição de verbos de escrita. Só as 4 já executadas na OLT real são aceitas por padrão; as demais exigem habilitação local para captura supervisionada.
- `docs/operations/OLT_QUERY_CATALOG.md` (mapa runbook→ID e processo de promoção) e ADR-0026 (Proposed). Inerte: nenhum fluxo chama `RunQuery`, sem endpoint/job/migração.

## Unreleased — PR 50 (leitura ativa de parâmetros do CPE, ADR-SD-002 item 4)
- Edge: `nbi.RefreshParams` (tarefa `getParameterValues` por grupo, só nomes da lista fechada, detecção de modelo de dados, limpeza de tarefas pendentes) e `RefreshGuard` (1 por dispositivo/10 min, 20/h, persistido antes de pedir). Config `refresh_tasks` (padrão **desligado**; exige `nbi_url` + `jobs_enabled`).
- Nuvem: o despacho de `refresh` de um CPE assina `target_ref` (id TR-069 do binding) no envelope; contrato `job-envelope` ganhou o campo opcional. `collect` e CPE sem binding seguem como antes.
- ADR-SD-002 → Accepted (autorização do responsável em 2026-10-29).

## Unreleased — PR 51 (reconciliação de tarefas do refresh ativo)
- Edge: depois de um POST ambíguo, de uma tarefa em fila/falha ou de id inválido, `RefreshParams` lista as tarefas do dispositivo, apaga só as que a própria chamada criou (mesmo nome e mesmos parâmetros, carimbo recente) e confirma por nova listagem. Motivo: no ensaio real o ACS criou a tarefa e fechou a conexão (EOF).

## Unreleased — PR 52 (conexões WAN de instâncias 1..4 no refresh ativo)
- Edge: o refresh lê PPP e IP (instância 1) de `WANConnectionDevice` 1..4 (a EG8145V5 real tinha a conexão PPP na instância 3); 11 tarefas por refresh em TR-098, `maxGroups` 12, conjunto exato fixado por teste. Freio: `nbi.RefreshHold` segura o dispositivo 24 h após qualquer refresh com fault.
- Medição real na LAB (ONT de bancada): `completed=11 faulted=0 readable_metrics=7`, 0 faults novos e 0 tarefas residuais no ACS. ADR-SD-002 atualizado (validade da faixa, carga, freio).

## Unreleased — PR 53 (`cpe_state`: estado WAN/Wi-Fi do CPE até a nuvem)
- Migração 0019 `cpe_state` (RLS forçada, CHECKs de métrica/escopo/tipo). `POST /v1/edge/cpe-state` (Edge → nuvem) e `GET /v1/cpes/{id}/state`; contrato OpenAPI atualizado.
- Edge: o coletor do GenieACS envia `cpe_state` depois do inventário (só dispositivos do inventário; falha de leitura não derruba o inventário); gateway ganhou o endpoint.

## Unreleased — PR 54 (R-D002 v1: WAN do CPE, ADR-0027)
- Regra pura `R-D002` v1 sobre o `cpe_state` (frescor POR LEITURA; sem leitura ou leitura antiga que possa esconder uma conexão estabelecida = `unknown`; todas as conexões recentes e não estabelecidas = hipótese `inferred` com confirmação humana; o enlace só é Up/Down se todas as leituras são recentes e concordam; a ONU só dá contexto observado). `POST /diagnostics/runs` aceita `cpe_id`/`onu_id` para regras de CPE, somente leitura, mesma flag.

## Unreleased — PR 55 (SD-PR-03: diagnostic_jobs passivos, ADR-0028)
- Migração 0020 `diagnostic_jobs` (imutável, RLS forçada, idempotência). `POST /v1/diagnostics/jobs` e `GET /v1/diagnostics/jobs/{id}` (flags `smart_diagnostics_jobs` + `diagnostic_engine`, desligadas por padrão): evidências do que já está retido (ONU e `cpe_state`), regras R-D001/R-D002 com entradas gravadas e replay, achados que citam evidência; dado antigo/ausente = `insufficient_evidence`. Operações movidas do overlay SD-001 para o contrato canônico.
- Correção de teste: a verificação "nenhuma rota do SD-001 existe" lia `app.routes` (neste FastAPI só mostra `/openapi.json`) e era vazia; agora usa o esquema OpenAPI gerado pela aplicação.

## Unreleased — ADR-0029 (Proposed): canal de execução das consultas da OLT
- Só documento (Codex approve em 5 rodadas): operação `olt_query` R0 sobre o catálogo do ADR-0026, intenção assinada estrita por consulta, sessão única do guard, estados duráveis com no máximo uma execução, instância única como pré-condição bloqueante, fencing e arrendamento em memória. Nenhum código, nenhuma execução na OLT; aguarda o aceite do responsável.

## Unreleased — ADR-0030 (Proposed): homologação em bancada
- Só documento (Codex approve em 6 rodadas): escopo restrito à ONT de bancada em três lugares independentes, conferência física antes de cada manobra, catálogo de manobras (H2 reboot, H3 SSID, H4 ONU na OLT), gate com seis condições (inclui autorização prévia de uso único), claim durável, trava de escrita e evidência verificável. Nenhum código, nenhuma escrita em equipamento.

## Unreleased — PR 56 (ADR-0030, H0 lado nuvem): gate de bancada
- Migração 0021: `bench_targets` e `bench_authorizations` (escritas só pelo owner CLI; o app lê, trava o alvo e consome a autorização) e `jobs.authorization_id`/`owner_epoch`. Flag `bench_writes` (desligada). `app/core/bench.py`: catálogo de manobras (`reboot_cpe` sem parâmetros), gate de seis condições fail-closed (flag, alvo de bancada destravado e Edge registrado, capacidade `observed` do perfil exato, parâmetros do catálogo, autorização PRÉVIA de uso único), `HOMOLOGATED_WRITES` continua vazio e bloqueia todo o resto.
- Jobs: aprovação mínima de 1 pessoa distinta; a autorização é consumida de forma atômica na aprovação; envelope assinado leva `authorization_id`, `authorization_ends_at`, `owner_epoch` e `target_ref`, com validade nunca maior que a janela; o despacho reverifica tudo; qualquer resultado que não seja sucesso confirmado, ou job despachado e nunca reportado, trava o alvo (`bench-unlock`).
- Owner CLI: `bench-target-add/remove`, `bench-authorize`, `bench-unlock`; `capability-set` de operação de bancada exige arquivo de evidência com todos os campos e nunca concede `certified`. Modelo em `docs/wiki/bench/TEMPLATE.md`.
- `bench.EDGE_SUPPORT = False`: o servidor, o owner CLI e os testes recusam habilitar, autorizar e despachar até o PR do Edge; envelope de bancada vive no máximo 2 min; `owner_epoch` nunca volta (tabela `bench_target_epochs`); nenhum envelope sai sem a transição DISPATCHED confirmada (Codex approve em 3 rodadas).
- Ainda NÃO feito (PR 57): lado Edge (configuração `bench`, conferência do CPE no ACS, claim durável, arrendamento) e a execução real da H2. Nenhuma escrita em equipamento.


## Unreleased — PR 57 (ADR-0030, lado Edge do gate de bancada + código do H2)
- Edge: `internal/bench` (runner), `jobs/claims.go` (claim durável), `jobs/lease.go` (lease assinada, só em memória), `nbi/bench.go` (identidade + única tarefa `reboot`), `BenchWriteOps` separado do `ReadOnlyOps`, seção `bench` na configuração, guard de ritmo próprio, execução fora do laço de poll.
- Nuvem: `X-Bench-Lease` em toda resposta de `jobs/next`; `bench.EDGE_SUPPORT = True` (precondição, não abertura: flag, alvo, registro e autorização prévia continuam exigidos).
- Runbook do responsável: `docs/wiki/bench/RUNBOOK-H2-REBOOT.md`. Emenda proposta no ADR-0030 (primeira execução).

## Unreleased — PR 58 (ADR-0030, primeira execução)
- Migração 0022: `bench_authorizations.first_run`. `bench-authorize --first-run`. O gate aceita, SÓ enquanto não há `observed`/`certified` completo, uma autorização `first_run` + entrada `supported`/`identified` completa do perfil exato; rechecado no despacho.

## Unreleased — PR 59 (Edge: firmware do CPE no snapshot)
- O coletor do GenieACS passa a ler `DeviceInfo.SoftwareVersion` do cache do ACS (GET, sem tarefa) e a enviá-lo como `firmware` no snapshot do CPE (identificador simples ou vazio). Necessário para o registro de capacidades casar firmware exato (ADR-0030).

## Unreleased — PR 61 (ADR-0030 H3 `set_wifi_ssid`, código; nenhuma manobra executada)
- Nuvem: `set_wifi_ssid` no catálogo de bancada com parâmetro `ssid` (formato fixo), `params` assinado no envelope, `bench-authorize --ssid`, hash da autorização ligado ao SSID.
- Edge: `nbi/bench_ssid.go` (lê original, grava registro de restauração, muda uma vez, lê de volta, restaura e lê de volta), `RestoreFile`, runner com resultado por etapa.

## Unreleased — PR 62 (Edge: ritmo da bancada configurável, motivo local da recusa)
- `bench.min_interval_seconds` (0 = 30 min; mínimo 60) e `bench.max_per_hour` (0 = 2; máximo 20) na configuração do Edge, a pedido do responsável durante a homologação; o padrão do produto continua 30 min. O Edge passa a logar localmente o motivo exato de cada recusa/falha de manobra (nada disso viaja à nuvem).

## Unreleased — PR 63 (ADR-0030 H4 `onu_reset` / `onu_deactivate`, código; nenhuma manobra executada)
- Nuvem: operações `onu_reset`/`onu_deactivate` (alvo = CPE de bancada, sem parâmetros), perfil de registro = o da OLT alcançada pelo vínculo ONU↔CPE confirmado, CLI aceita os pares `olt`.
- Edge: `internal/olt/bench.go` (lista fechada e exata de comandos, identidade na mesma sessão, reativação sempre, recuperação), `collector.OLT.Exclusive` (mesmo guard das coletas), seção `bench.olt`, execução do runner com ritmo e autorização gastos só depois da identidade.

## Unreleased — PR 67 (Edge: cooldown pós-falha da bancada configurável)
- `bench.olt.cooldown_seconds` (0 = 900; 60..900): quanto tempo a OLT fica em paz depois de uma sessão de manobra que FALHOU. O padrão continua 15 min; fica no guard compartilhado com as coletas. Antes, uma parada na confirmação ou numa checagem cobrava 15 min de espera a cada tentativa da homologação.

## Unreleased — PR 68 (relatório de ONUs offline há mais de X horas)
- `GET /v1/onus/offline?min_hours=24&olt_id=&pon_path=&include_stale=&format=json|csv&limit=` (inventory:read, somente leitura, sem migração): as ONUs fora do ar há pelo menos X horas, as mais antigas primeiro, por OLT/PON, com exportação CSV. O início da queda traz a BASE (`transition_observed` exato; `since_last_online` = no máximo isso); ONU nunca vista online só é contada em `excluded.unknown_start`; dado de OLT sem coleta recente fica fora (`excluded.stale`) salvo `include_stale=true`. Sem dado pessoal (serial, OLT, PON). CSV neutraliza fórmulas de planilha.


## Unreleased — "Last down time" da OLT
- Edge: lê por SNMP (somente leitura, lotes de 20) o "Last down time" das ONUs offline e envia `last_down_at` no snapshot.
- API: migração 0023 `onus.olt_down_at`; `GET /v1/onus/offline` ganha a base `olt_reported` (abaixo de `transition_observed`, acima de `since_last_online`). `down_since` não muda de significado.
- Edge: `last_down` (opcional, entrada CLI Huawei R015): lê o "Last down time" por SNMP depois da coleta CLI, no máximo 1×/h, só nas PONs com ONU offline; o horário vai como `last_down_at` no snapshot seguinte. Sem segunda entrada de OLT.

## Unreleased — PR 74
- Edge: "Last down time" da OLT por CLI (`down_times` na entrada CLI R015): `display ont register-info` na mesma sessão da coleta, só ONUs offline, até `max_per_round` por coleta; exclusivo com `last_down` (SNMP, não homologado na OLT real). Parser falha fechado (todo registro bem formado, maior UpTime decide).

## Unreleased — PR 81
- API: migração 0025. MFA recente (10 min): `POST /v1/auth/mfa/step-up`, `mfa_at` na sessão, `403 mfa_recent_required` nas permissões `mfa_recent` (ligada por padrão; `MFA_RECENT_ENFORCE`/`MFA_RECENT_SECONDS`). Delegação da plataforma (até 8 h, com motivo): `GET/POST /v1/platform-delegations`, `DELETE /v1/platform-delegations/{id}`, permissão `platform:delegate` (só `isp_admin`); `platform_support` deixa de ser membership e só existe por delegação viva conferida a cada requisição; CLI `platform-operator`.
- Web: seção de acesso temporário em Administração → Papéis e permissões e confirmação do segundo fator dentro da ação.

## Unreleased — PR 82
- API: `GET /v1/cpes/{id}/actions` e `POST /v1/cpes/{id}/actions/{reboot_cpe|set_wifi_ssid}`; permissões `devices:act:reboot_cpe` (isp_admin, engineer, noc_n2) e `devices:act:set_wifi_ssid` (isp_admin, engineer). O pedido reaproveita preview+submit do motor de jobs (nenhum caminho novo de escrita; `HOMOLOGATED_WRITES` continua vazio) e é recusado antes de criar job se o registro não tem entrada observada para o perfil.
- Web: card **Ações** no detalhe do CPE.

## Unreleased — PR 83
- API: migração 0026. `POST/GET /v1/bench/authorizations`, `DELETE /v1/bench/authorizations/{id}`; permissão `bench:authorize` (noc_n2, engineer, isp_admin; OLT-side só engineer/isp_admin); funções SQL `app_bench_authorize`/`app_bench_revoke` (conexão dedicada). O motor de jobs recusa (`authorizer_not_independent`) autorização da API em job cujo solicitante/aprovador é o autorizador.
- Web: card **Autorização de bancada** no CPE de bancada.

## Unreleased — PR 84
- API: migração 0027. `GET /v1/team`, `GET /v1/team/activity`, convites por link (`POST /v1/team/invites`, `.../renew`, `DELETE`), `POST /v1/team/members/{id}/password-reset` e `/remove`, páginas públicas da API `GET|POST /v1/invites/{token}[/accept]`, `POST /v1/auth/password`. Funções SQL `app_invite_*`, `app_reset_create`, `app_member_remove`, `app_password_change` (conexão dedicada).
- Web: **Administração → Equipe e acessos** substitui Membros e Papéis (as URLs antigas redirecionam); página pública `/convite/[token]`; trocar a senha em Conta → Segurança da conta. Funções e permissões em linguagem de capacidade.

## Unreleased — fix MFA só no login
- `MFA_RECENT_ENFORCE` passa a vir desligada (decisão do responsável): o código do segundo fator é pedido ao entrar, não a cada ação. O mecanismo de step-up continua disponível por chave. Equipe e acessos: atalho "Minha segurança" e aviso para ativar o MFA.

## Unreleased — PR 85 (onu_state_events)
- API: migração 0028 `onu_state_events` (histórico de mudanças de estado das ONUs, escrito só por gatilho em `onus`; a role da aplicação só lê; baseline por ONU no instante da migração; ordem por `seq`, `at` nunca recua; retenção `onu_state_events_prune(>=370 dias)` só pelo dono do banco). `GET /v1/onus/{id}/history`, `GET /v1/onus/unstable`; o relatório `GET /v1/onus/offline` (JSON e CSV) ganha `drops_30d` e `offline_hours_30d`.
- Web: coluna "Últimos 30 dias" no relatório de ONUs offline e cartão "Histórico (30 dias)" na ONU 360.

## Unreleased — PR 86 (olt_query, metade da nuvem; ADR-0029)
- API: operação `olt_query` (R0, alvo OLT, sem aprovação) no motor de jobs; intenção fechada por consulta (`query_id` + exatamente os inteiros do escopo; `olt_ref` e `catalog_version` acrescentados pela nuvem e cobertos por hash, auditoria e assinatura). `GET /v1/olts/{id}/queries` (catálogo como o chamador o vê) e `POST /v1/olts/{id}/queries/{query_id}`. Permissão `olt_query:run` (isp_admin, engineer, noc_n2), flag `olt_query` (desligada), cota por hora (10 por usuário, 60 por provedor, 20 por OLT; 429), rollout só `olt.version` e `olt.board`. O catálogo da nuvem é comparado por teste ao do Edge (`query.go`).
- **Inerte por desenho:** o canal do Edge (fila persistente, arrendamento, parsers) ainda não existe, então `olt_query.EDGE_SUPPORT = False`: nada é oferecido, nenhum job é criado, a CLI `feature-set olt_query on` recusa e o despacho ignora `olt_query`. Contrato do envelope atualizado (`operation` e `params`).

## Unreleased — PR 87 (olt_query, fatia 2: Edge, envelope e fila durável; ADR-0029)
- Edge: `olt.ParseIntent` (intenção fechada por escopo, inteiros decimais, `olt_ref` UUID, `catalog_version`) e `olt.CatalogVersion()` (fixados por teste contra o valor que a nuvem calcula). `jobs.Verifier` aceita `olt_query` só com a chave local ligada, verificador de intenção ligado e a operação em `allowed_operations`; recalcula o `intent_sha256` sobre os `params` carregados (`jobs.IntentHash`, vetor fixado contra o Python). `Envelope.Params` passou a `jobs.Params` (valores tipados) para carregar inteiros.
- Edge: pacote `internal/oltquery`, fila durável (JSON 0600, fsync + rename) com `QUEUED→CLAIMED→EXECUTED|FAILED→REPORTED`, `EXPIRED` e `UNKNOWN`; CLAIMED é gravado antes de qualquer I/O, um CLAIMED após reinício vira UNKNOWN e nunca roda de novo; orçamento 5 por sessão e 20 por hora por OLT no mesmo arquivo; arquivo ilegível = orçamento gasto; aborto de lote; reenvio de relatórios sem executar nada.
- Ainda NÃO ligado ao executor da OLT nem ao laço de jobs do Edge: nada chama a fila (fatia 3).

## Unreleased — PR 88 (olt_query, fatia 3: executor no Edge e resultado tipado; ADR-0029)
- Edge: `collector.Queries` executa as consultas aprovadas DENTRO da sessão CLI da própria coleta (mesma reserva, intervalo e cooldown do guard), depois dos comandos da coleta e sem poder falhar a coleta; `HuaweiR015.RunQueryInConfig` (não reenvia `enable`/`config`, o snapshot R015 termina em config); parsers tipados de `olt.version` e `olt.board` (validados contra as capturas reais; a saída crua nunca sai do Edge); falha do equipamento aborta o lote (`olt_busy`); motivos são categorias, nunca texto do equipamento.
- Edge: chave local `olt_query_enabled` + `olts[].cloud_id` + `olt_query` em `allowed_operations` (validados juntos, desligado por padrão); `PollJob` enfileira o envelope (nada roda ali) e `reportQueries` entrega o resultado tipado pela fila de entrega (UNKNOWN após reinício vai como `postcheck_ok=false`).
- API: `POST /v1/edge/jobs/{id}/result` aceita `data` só para `olt_query` bem-sucedida e confere o formato fechado da consulta; formato diferente vira FAILED `invalid_result` e não é armazenado.
- Continua INERTE na nuvem (`EDGE_SUPPORT=False`) e nada foi executado em OLT real.

## Unreleased — PR 89 (olt_query, fatia 4: arrendamento e geração de propriedade; ADR-0029 item 3)
- API: migração 0029 (`olts.owner_epoch`, `transfer_to`, `transfer_started_at`, `lease_until`; a role da aplicação perde o UPDATE/INSERT amplo em `olts` e fica só com as colunas da ingestão e do arrendamento). `X-OLT-Lease` (schema `olt-lease/1`, assinado, 2 min) em TODA resposta de `/v1/edge/jobs/next`, listando só as OLTs do Edge, sem transferência em curso, com flag e canal ligados. O envelope de `olt_query` carrega `owner_epoch` e vive no máximo 10 min; o despacho cancela a consulta se a OLT mudou de dono ou está em transferência.
- CLI do dono: `olt-transfer-start` (fase 1: sem arrendamento nem despacho, consultas abertas terminam) e `olt-transfer-finish` (fase 2: só depois do último arrendamento do dono antigo + 60 s; dono novo, época + 1).
- Edge: `LeaseHolder` ganhou a família `olt-lease/1` (um arrendamento de uma família nunca vale para a outra) e `Epoch()`; a fila grava a maior época vista por OLT e recusa envelope de época menor (`stale_owner`); o executor só reivindica com arrendamento válido da OLT, confere a época da própria consulta no claim e não envia nada se o arrendamento acabou. Arrendamento só em memória.
- Continua INERTE (`EDGE_SUPPORT=False`); a liberação explícita pelo Edge antigo (3(a)) não foi implementada: esperar o arrendamento vencer é sempre seguro.
- PR 89, Codex r1: o fim do arrendamento é calculado UMA vez (segundos inteiros) e é o mesmo valor assinado e gravado em `lease_until`; uma OLT só entra no arrendamento se a gravação der certo (transferência concorrente a tira); o Edge recusa arrendamento cujo `issued_at` difere do relógio local em mais de 45 s (a espera de 60 s do fim da transferência cobre esse desvio). Um envelope já despachado conta como EM VOO: o Edge só o executa com arrendamento válido, que a fase 1 deixa de renovar e a fase 2 espera vencer. Snapshots: o dono atual segue reportando durante a fase 1; depois do fim o Edge novo é aceito e o antigo recebe 409 (teste).

## Unreleased — PR 90 (olt_query, fatia 5: canal ligado no código; ADR-0029 item 7)
- `olt_query.EDGE_SUPPORT = True`: o canal existe de ponta a ponta. Nada é oferecido nem despachado enquanto a flag `olt_query` do provedor estiver desligada (continua assim por padrão) e cada Edge só roda consultas com `olt_query_enabled`, `olts[].cloud_id` e `olt_query` em `allowed_operations`. Rollout só `olt.version` e `olt.board`.
- Edge do LAB reimplantado com o binário que entende o canal (versão `0.1.0-lab-9242b01`), configuração inalterada (canal desligado) até o ensaio supervisionado, autorizado pelo responsável em 2026-10-30.
- PR 91: ensaio supervisionado na OLT real do LAB concluído com `olt.version` e `olt.board` (ver TEST_EVIDENCE); a vida do envelope de `olt_query` passou de 10 para 20 min e a do job para 22 min: pior espera = intervalo de 15 min + coleta de ~3 min antes das consultas (~18,5 min); as demais operações seguem com 15 min.

## Unreleased — retenção agendada do histórico de ONUs
- `scripts/retention-scheduled.sh` + entrada no cron do LAB (03:45): poda diária do `onu_state_events` (mantém 400 dias e o estado de partida da janela). Medição de desempenho do `/v1/onus/unstable` com 30 mil ONUs e 1,23 milhão de eventos em `TEST_EVIDENCE`.

## Unreleased — PR 94 (tela de consultas da OLT)
- Web: cartão da OLT em **Rede** ganha **Consultar a OLT…** (gaveta): lista as consultas oferecidas ao papel (com o motivo das indisponíveis), pede UMA consulta somente leitura e acompanha o job a cada 10 s (a consulta roda na próxima janela da coleta, até ~18 min); mostra só o resultado TIPADO (versão/uptime; placas e slots vazios) e categorias de falha explicadas; resultado fora do formato é descartado, texto livre do equipamento nunca é renderizado. BFF: `GET /bff/olts/{id}/queries`, `POST /bff/olts/{id}/queries/{q}`, `GET /bff/jobs/{id}` (só olt_query; só estado, categoria e resultado).
- Teste: `e2e/olt-queries.spec.ts` (projeto `consultas`: flag desligada, fluxo com resultado, falha e resultado inválido, erro de cota; axe) e verificação sem mocks na stack efêmera (o job nasce com a intenção fechada). Ajuda: `rede/consultar-olt` (rascunho).

## Unreleased — PR 95 (Edge: modo captura supervisionada, ADR-0032 item 1)
- Edge: `olts[].capture` lista consultas AINDA NÃO validadas a capturar UMA vez, dentro da própria sessão da coleta, depois da fila de `olt_query`. A saída crua vai só para `captures/` ao lado da fila do Edge (diretório 0700, arquivos 0600, apagados após 24 h, no máximo 10 arquivos / 20 MiB); nada vai para a nuvem, para a fila de relatórios, para o log (só id, bytes, duração e categoria).
- Orçamento próprio e persistido (`ReserveCapture`): 2 capturas por sessão e 4 por hora por OLT, somado às consultas sob demanda nunca passa de 8 por sessão; orçamento gasto sobrevive a reinício; arquivo da fila ilegível = orçamento gasto. Marcador `done.json` gravado ANTES da saída: cada captura roda uma única vez. Primeira anomalia (recusa do equipamento, erro, sem lease, fim da janela) encerra o lote.
- Config: `capture` exige `olt_query_enabled`, `cloud_id` e OLT CLI `huawei_ma56_r015`; no máximo 10; id do catálogo, parâmetros no escopo, sem duplicata; escopo PON/ONU só na PON/ONU da bancada (`bench.olt`). Remover `capture` e reiniciar o Edge revoga.
- Correção: `Store.load` de arquivo inexistente não inicializava os mapas de capturas (panic na primeira reserva).

## Unreleased — PR 96 (ERP Hub: HubSoft primeiro, HS-01 + HS-02, ADR-0033)
- Decisão de produto: ordem de homologação HubSoft (P0) → IXC (P1) → SGP (P2); IXC/SGP ficam no registro sem conector real. Somente leitura; nada é escrito no ERP.
- Migração 0030 `erp_connections` (RLS forçada, sem DELETE, a aplicação só atualiza estado/`enabled`). `app/core/erp_hub.py` (registro, guarda de URL com lista do operador, resolução só para endereço público, segredo por referência em arquivo 0600 por tenant), `app/integrations/hubsoft.py` (token OAuth com cache, 401 reautentica uma vez, 403 final, 429 com `retry_after`, 5xx com jitter, limites próprios, sem redirecionamento), `/v1/integrations/erp` (listar, criar, testar, ligar, desligar), flag `erp_hubsoft` (desligada), permissões `erp:manage` e `erp:test` (só `isp_admin`). **Nada disto foi exercitado numa instância HubSoft real**: só mocks.

## Unreleased — PR 97 (consultas da OLT: lote 1 validado, ADR-0032 item 2)
- Capturas reais do lote 1 na OLT do LAB (MA5608T, MA5600V800R015C00) viraram fixtures (`display_time.txt`, `display_data_sync_state.txt`, `display_temperature_0.txt`), parsers tipados fechados no Edge e validação do mesmo formato na nuvem; `olt.time`, `olt.sync` e `olt.temperature` passam a `Validated` e entram no `ROLLOUT` (a versão do catálogo mudou nos dois lados). A tela mostra hora da OLT (com o fuso dela), reserva de controle "ausente ou com falha" (a resposta não distingue) e a temperatura por placa.
- **Ordem de implantação:** a versão do catálogo mudou (depende dos flags `validated`) e o Edge recusa intenção de outra versão. Implantar o Edge novo PRIMEIRO e a nuvem em seguida; consultas pedidas na janela entre os dois falham com categoria (nada é repetido) e podem ser pedidas de novo. Reverter segue a ordem inversa.
- Achado da captura: `olt.alarm.active` pagina (a saída para no "More") e o Edge, por regra, recusa saída paginada: segue não validada; `olt.autofind` espera a janela de orçamento (4 capturas/h).

## Unreleased — PR 98 (cache primeiro das consultas à OLT, ADR-0032 item 4)
- Migração 0031: `olt_query_latest` (último valor tipado por OLT + consulta + parâmetros, RLS forçada, ordem por `(owner_epoch, asked_at)`: um resultado atrasado de pergunta mais antiga não regride o cache) e `olt_metric_samples` (série; a temperatura por placa alimenta `board_temp_c`). O resultado de um job de `olt_query` só entra no cache enquanto o Edge que reportou ainda é o dono da OLT.
- API: `POST /v1/olts/{id}/queries/{q}` responde `outcome: "cached"` (sem criar job) quando há valor dentro do TTL e as MESMAS comportas de um job (flag, rollout, canal) estão abertas; `refresh: true` pergunta de novo com cota própria de 3 por hora por OLT (`olt_query_refresh_quota`); novo `GET /v1/olts/{id}/queries/{q}/latest` devolve o valor com a idade e `stale`. Tela: "Dado guardado, há N min" e "Atualizar agora".
- Fica para o item 5 (rotinas do Edge): rota de ingestão do Edge com `seq` e a poda de 400 dias de `olt_metric_samples`; hoje só jobs alimentam as tabelas, então o volume é desprezível.

## Unreleased — PR 99 (ONT Configuration Manager, leitura: FC24-00/01, ADR-0034)
- Adendo v2.4 incorporado sem reiniciar a sprint: GAP (`docs/addenda/v2.4/GAP_ANALYSIS.md`), ADR-0034, backlog FC24-* e cópias de referência do pacote. Migração 0032 `cpe_config_fields`; `app/core/ont_config.py` (catálogo fechado de campos canônicos, capacidades derivadas do observado, formulário dinâmico); `POST /v1/edge/cpe-config`; `GET /v1/cpes/{id}/ont-config/{configuration,capabilities,form-schema}`, `GET /v1/ont-config/health`; flag `ont_config` (desligada); CLI `ont-config-mock` (perfis SINTÉTICOS rotulados).
- Somente leitura: `write_allowed` é falso para toda capacidade; senha só como "definida?"; óptica sem capacidade de escrita. **Nenhum dado de ONT real foi lido nem escrito**: o Edge ainda não reporta `cpe-config` (FC24-04).

## Unreleased — PR 100 (ONT Configuration Manager, sidebar: FC24-02)
- Web: botão **Configuração do aparelho** no cartão do roteador da ONU 360° (só com `ont_config` ligado e vínculo ONU↔CPE confirmado) abre um painel direito recolhível e NÃO modal: miniatura SVG, identidade, frescor, abas Resumo (óptica somente leitura) / Wi-Fi (seletor da rede real) / LAN / WAN geradas do que a API observou, aviso de dados sintéticos, estados sem dado/defasado/erro, Esc recolhe e devolve o foco. Nenhum botão de escrita. BFF `GET /bff/cpes/{id}/ont-config` repassa só o formato fechado.
- `seed_demo.py`: CPE `DEMOA0002` + `ont_config` ligado + perfil sintético `dualband` (alvo do e2e). Playwright: projeto `aparelho` (2 casos, axe e celular). Ajuda `ont/consultar-configuracao` em rascunho (captura real pendente).

## Unreleased — PR 101 (ONU Quick Inspector, UX 2.2, ADR-0035)
- Web: resumo rápido da ONU em painel direito não modal (≥1024 px; <1024 px a gaveta modal) aberto pela lista de Rede, com miniatura genérica, Registro PON (OLT) e Comunicação ACS separados, RX com origem e sem severidade inventada, OLT/PON, cliente só se autorizado e confirmado, frescor e "Abrir Visão 360°". Trocar de ONU cancela o pedido anterior. BFF `GET /bff/onus/[id]/quick` compõe as rotas existentes (nenhum endpoint novo). Flag `onu_quick_inspector` (desligada; desligada = resumo antigo idêntico). `DeviceThumbnail` compartilhada com o sidebar de configuração do aparelho.
- Demo/seed: `OLT-QUICK-01/02` (DEMOQ0001 recente, DEMOQ0002 com coleta de 3 h) e a flag ligada; `app.spec.ts` ajustado ao painel novo. Ajuda `rede/resumo-da-onu` em rascunho. Playwright: projeto `inspetor`.

## Unreleased — ONT Configuration Manager, pré-visualização (FC24-03)
- ADR-0036; migração 0033 `cpe_config_changes`; `POST/GET /v1/cpes/{id}/ont-config/changes/*` (pré-visualização, leitura, submissão que sempre bloqueia). Permissões `ont_config:request` e `ont_config:request_high`. Nada executa em equipamento; flag `ont_config` segue desligada.

## Unreleased — Gestão de ONUs (ADR-0037)
- Rede reconstruída no padrão do protótipo Lovable: matriz de PONs, árvore OLT/PON, lista com filtros e painel de detalhes ao lado (nunca sobreposto), abas Resumo/Aparelho/Histórico, painéis frontais conceituais; ONU 360° com trilha e painel frontal. BFF `GET /bff/onus/{id}/history`. Atrás da flag `onu_quick_inspector`.
- Inventário: janela de dado recente da OLT de 15 para 35 min (2 coletas + folga; CPE/ACS seguem 15 min); coleta de 25 min atrás é recente, de 40 min é defasada.


## Unreleased — Speed Diagnostics TR-143, metade da nuvem (PR 1, ADR-0038)
- Migração aditiva 0034: `speed_endpoints` (destinos LÓGICOS, sem coluna de URL/endereço/credencial) e `speed_test_runs` (uma linha por direção, com o número calculado pela nuvem; CHECK impede figura sem medição e zero). RLS forçada; a aplicação só lê os destinos; o dono escreve por `speed-endpoint-set`.
- Operações `speed_test_download`/`speed_test_upload` no motor de jobs e no **catálogo de bancada** (emenda ao ADR-0030): só o CPE de bancada, parâmetros `{target, profile}` fechados, autorização prévia de uso único; `HOMOLOGATED_WRITES` segue vazio. Condição extra do gate: `speed_test_redirect_probe` ou `speed_test_egress_acl` no registro, com evidência (`redirect_unverified`).
- `app/core/speed.py`: `compute()` puro (DL/UL, parcial < 3 s ou < 95 % do perfil, inconclusivo, nunca zero), formato fechado do relatório do Edge, limites 1/ONT · 1/PON (vínculo ONU↔CPE confirmado) · 2/provedor sob trava transacional.
- Rotas (todas 403 `feature_disabled` com a flag `speed_diagnostics` desligada, padrão): `GET /v1/cpes/{id}/speed/capabilities|runs|runs/{id}`, `POST /v1/cpes/{id}/speed/runs`, `GET /v1/speed/health`. Permissão `diagnostics:speed_run` (isp_admin, engineer, noc_n2); autorizar a manobra por API: engineer e isp_admin.
- `bench.SPEED_EDGE_SUPPORT = False`: sem a metade do Edge (PR 2) nada é autorizado, aprovado nem despachado.
- Nada foi executado em ONT, OLT ou ACS reais.

## Unreleased — Speed Diagnostics TR-143, metade do Edge (PR 2, ADR-0038)
- Edge (Go): `internal/speed` (catálogo local de destinos com validação SSRF, perfis fechados, sonda de saúde, três URLs fixas), `internal/nbi/speed.go` (um único `setParameterValues`, leitura só do objeto TR-143, sem reenvio, resultado antigo ignorado), ramo de teste de banda no `bench.Runner` (lease, identidade no ACS, pacing em disco, claim durável), envelope `speed_test_*` verificado com nomes lógicos e hash de intenção, seção `speed` da configuração, relatório de saúde dos nós, `data` no resultado do job.
- Nuvem: `bench.SPEED_EDGE_SUPPORT = True` (flag `speed_diagnostics` segue desligada); migração 0035 (cada destino é vinculado a um Edge dono; o Edge atualiza só `health`/`health_at` dos seus); `POST /v1/edge/speed-health`; CLI `speed-endpoint-set --edge`; nó só "pronto" com palavra `ok` recente (30 min); contrato `job-envelope.schema.json` com as operações e o formato `{target, profile}`.
- Docs: seção "Metade do Edge" no ADR-0038 e `docs/addenda/v2.2-speed/EDGE_CONFIG.md`. Nenhum Edge reimplantado; nada executado em ONT/ACS reais.

## Unreleased — Speed Diagnostics TR-143, UX, ajuda e homologação (PR 3, ADR-0038)
- Web: aba **Teste de banda** no painel da ONU e cartão na ONU 360° (`SpeedTestSection`), atrás da flag `speed_diagnostics`; rotas BFF `/bff/cpes/{id}/speed` e `/speed/runs` (formato fechado, só nomes lógicos); estado indisponível com motivo; resultado com confiabilidade; "—" no lugar de zero.
- Ajuda: artigo `rede/testar-banda` + manifesto (capturas reais do estado indisponível e capturas de cenário rotuladas como simuladas); `docs/operations/SPEED_HOMOLOGACAO.md` (guia e planilha vazia). `scripts/seed_demo.py` liga a flag só no demo (a tela), sem liberar teste.
- Nada executado em ONT/ACS reais; nenhuma implantação feita.

## Speed Diagnostics — aceite do risco de 3xx na bancada (ADR-0038, emenda aprovada em 2026-10-31)
- Migração 0036 `speed_risk_acceptances` e a opção C no gate (`speed.redirect_basis`): destino CORE nomeado, firmware exato, validade ≤ 90 dias, sonda `unsupported` registrada, revogação serializada com o despacho. Owner CLI `speed-acceptance-set|revoke|audit`. A flag `speed_diagnostics` segue DESLIGADA; nada executado em equipamento por este PR.

## QoS-001 PR A — leitura de qualidade passiva (ADR-0039, flag OFF)
- `GET /v1/cpes/{id}/quality/capabilities`, `POST|GET /v1/cpes/{id}/quality/runs[/{run}]`; migração 0037 `quality_runs` (imutável, RLS forçada); permissões `diagnostics:quality_*`; flags `quality_diagnostics|quality_full|quality_active_tests` (todas OFF). Só dados já retidos (ACS em cache, OLT); o COMPLETO referencia um grupo do SD-001, não inicia teste. Sem ping/DNS/traceroute nesta entrega.

## QoS-001 PR B — aba "Qualidade" e ajuda (ADR-0039, flag OFF)
- Web: aba **Qualidade** no painel da ONU e cartão na ONU 360° (`QualitySection`, `lib/quality.ts`) atrás da flag `quality_diagnostics`; rotas BFF `/bff/cpes/{id}/quality` e `/quality/runs` (formato fechado, só a chave de idempotência sai do navegador). Estado geral em três valores, quatro indicadores, hipóteses com ressalva e "Ver detalhes por camada"; sem dado = "Sem leitura" (nunca zero); leitura antiga marcada como antiga; nível óptico sem perfil homologado aparece como "sem faixa de referência", não como "ok". A leitura COMPLETA continua só na API.
- Ajuda: artigo `rede/qualidade-do-servico` + manifesto (capturas reais e capturas de cenário rotuladas como simuladas); `docs/operations/QUALITY_HOMOLOGACAO.md` (guia e planilha vazia). `scripts/seed_demo.py` liga a flag só nos dados sintéticos.
- Nada executado em ONT/ACS reais; nenhuma implantação feita.

## Speed — 1ª execução real de download na bancada (2026-10-31)
- Connection Request da ONT de bancada corrigido pelo padrão do ACS (credencial por dispositivo, remoção de `cwmp.connectionRequestAuth`; provision `inform` pulando `PeriodicInformTime` só para o fabricante ALCL). Download real de 10 MB executado e concluído (PARCIAL, `too_short`). O registro `speed_test_download` segue `supported`/`identified` com esta evidência; a promoção a `observed` aguarda o aceite escrito do responsável (uma promoção prematura foi revertida). Nada de produção afetado; flag `speed_diagnostics` desligada ao fim.

## Speed — `speed_test_download` observed e 1ª medição confiável (2026-10-31)
- Aceite do responsável registrado ("aceito download") e `speed_test_download` promovido a `observed` para Huawei EG8145V5 `V5R019C10S350`. Download de 200 MB na bancada: 331,15 Mbps em 4,96 s, `completed`. Faltam repetições, referência cabeada e upload. Flag `speed_diagnostics` desligada; nada de produção afetado.

## Speed — 3 repetições de download e H1 do upload (2026-10-31)
- 3 downloads de 200 MB na bancada, todos `completed` (331,15 / 330,83 / 380,93 Mbps). H1 de leitura do `UploadDiagnostics`: folhas necessárias presentes; `speed_test_upload` registrado `supported`/`identified` (não observado). Faltam referência cabeada, upload real (precisa da autorização `--first-run`) e relatório periódico.

## Edge — `bench.read_only_onus` e H1 de vínculo da ZTE (2026-10-31)
- Edge: nova lista `bench.read_only_onus` (até 4 ONUs de bancada adicionais, só para capturas de LEITURA, escopo de ONU com posição exata, nunca PON, sem manobra). Implantado no LAB (`0.1.0-lab-9ec5221`).
- Captura supervisionada de 2 consultas da ONT 11 da PON 0/0/14 e `docs/wiki/bench/H1-vinculo-zte-f670l-2026-10-31.md`: a OLT registra tipo `F670LV9.0` e serial GPON compatíveis com a ZTE do ACS. Vínculo apenas sugerido (não confirmado); nenhuma ZTE cadastrada como alvo de bancada.

## Bancada: ZTE F670L cadastrada, firmware ZTE no Edge e Nokia com Connection Request (2026-11-01)
- ZTE F670L: aceite do responsável e autorização de escrita no chat (registrados no ADR-0030). Um `bench-target-add` feito ANTES do vínculo foi revertido para cumprir a ordem do ADR; o alvo só entra depois que uma pessoa confirmar o vínculo. `reboot_cpe` registrado `supported`/`identified` para ZTE F670L `V9.0.11P1N10B`. NENHUMA manobra foi executada nela. Novo comando do dono `onu-cpe-link-suggest` (vínculo sugerido com evidência, nunca confirma).
- Edge `0.1.0-lab-777ec89`: aceita o formato de firmware ZTE (`V<n>(.<n>){1,3}P<n>N<n>[A-Z]?`, gramática estrita); a ZTE está em `bench.devices` do Edge (lista local; o alvo na nuvem só depois do vínculo); lista `capture` retirada. Pendência conhecida do filtro genérico `firmwareToken` em `KNOWN_ISSUES.md`.
- ACS: provision `inform` usa o serial como usuário de Connection Request só para o fabricante ALCL (Nokia); o Connection Request da Nokia passou a funcionar.

## Speed: `speed_test_upload` da ZTE F670L promovido a `observed` (2026-11-01)
- Aceite do responsável pelo chat ("Aceito upload ZTE") sobre o upload de 200 MB (`completed`, 346,17 Mbps), gravado no próprio documento de evidência. Promoção feita no registro da LAB pelo owner CLI com `--evidence-file` (todos os campos checados). Escopo: UMA execução confiável; repetições, referência cabeada, multiconexão e identidade física seguem sem validação. Nada de produção afetado.

## Ping: primeiro ping real mostrou que o IPPing termina em `Complete` (2026-11-01)
- Implantação na LAB: migração 0038, API e web, Edge `0.1.0-lab-74719f0` com `ping_test`, destino lógico `core-lab` e capacidades `ping_test` (`identified`) na ZTE e na Huawei. O 1º ping real na ZTE F670L: o aparelho mediu (5 de 5, 11/11/12 ms), mas informa `DiagnosticsState = Complete`; o Edge só aceitava `Completed` e o job falhou por `timeout` (alvo travado e depois destravado com motivo). Correção no Edge: `Complete` é terminal e sai como `Completed`; o estado terminal do ping é lido estritamente depois do pedido. O fake dos testes usava `Completed` e não pegou isso: só o aparelho real.

## ACS: rotação do `cwmp.auth`, fase 1 (2026-11-01)
- Medição das últimas 24 h: só as duas ONTs de bancada informam com autenticação aceita. Fase 1 aplicada: o ACS aceita o par antigo E um par novo (gerado e guardado fora do repositório); backup 0600 da config; testes de credencial ausente/errada (401) e Informs reais das duas ONTs de bancada continuaram aceitos. Faltam a fase 2 (configurar o par novo nas ONTs, por alguém na bancada) e a fase 3 (remover o par antigo). Detalhes em `docs/operations/GENIEACS_CWMP_AUTH_ROTATION.md`.
