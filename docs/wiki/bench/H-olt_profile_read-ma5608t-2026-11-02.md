# Leitura de perfis da OLT (`olt_profile_read`) — Huawei MA5608T, MA5600V800R015C00 — 2026-11-02

Evidência da leitura SOMENTE LEITURA dos perfis da OLT do LAB, pelos dois caminhos do produto. Autorização do responsável: mensagem do chat de 2026-11-02 ("Autorizado. Capture"), dentro do ADR-0032 (captura supervisionada) e do ADR-0040 (fase somente leitura). Nenhum comando de escrita foi enviado; `HOMOLOGATED_WRITES` segue vazio.

## O que foi feito
1. **Captura supervisionada** (ADR-0032, lote 3), Edge `0.1.0-lab-f9479ac`: `display ont-lineprofile gpon all`, `display ont-srvprofile gpon all`, `display dba-profile all` e `display traffic table ip from-index 0` executados uma vez cada, na sessão da coleta. Saída crua só no host do Edge (0600), conferida contra os parsers localmente e depois apagada (`shred`) no Edge e na cópia local. Resultado: 41 perfis de linha e 34 de serviço (conferidos contra a linha `Total`), 18 perfis DBA (tabela fechada pela regra final) e 14 tabelas de tráfego (conferidas contra `Total Num`).
2. **Caminho de produção** (Edge `0.1.0-lab-ba2e3be`): quatro jobs `olt_query` pedidos à nuvem por conta de serviço descartável (desativada ao fim), executados pelo Edge na janela seguinte, resultado tipado fechado devolvido e guardado no cache (`SUCCEEDED` x4). Nomes de perfil de linha/serviço chegaram NULOS à nuvem (opt-in `olt_profile_names_to_cloud` desligado).
3. **Sync** (`POST /v1/olts/{id}/profiles/sync`): 18 snapshots `edge_read` PARCIAIS dos perfis DBA (tipo, taxas fixa/garantida/máxima, nº de ONUs que usam). Idade da leitura medida pela hora da pergunta.

## Escopo e limites (o que NÃO foi lido)
- Foi lida a LISTA de perfis de linha/serviço (número, nome e nº de ONUs), NÃO o detalhe (T-CONT, GEM, VLAN, portas). Por isso nenhum snapshot de linha/serviço foi criado e os snapshots DBA ficam `partial` (o resto vai em `unknown_fields`): a plataforma não afirma equivalência nem reuso a partir deles.
- Só vale para `MA5608T` / `MA5600V800R015C00`. Outra release R015 é recusada pelo Edge sem enviar comando.
- Não houve ONU em autofind na OLT durante as capturas (`olt.autofind` vazio): o formato de uma entrada real de autofind continua NÃO observado.

## Versões
Edge `0.1.0-lab-f9479ac` (captura) e `0.1.0-lab-ba2e3be` (produção do job); API na `main` (catálogo `a02548436a03…`); OLT `MA5608T` / `MA5600V800R015C00`.

## Aceite
Registrada a entrada de capacidade `olt_profile_read` = `supported` / `observed` para este fabricante, modelo e firmware, com estes limites. A promoção a `certified` exige o detalhe de linha/serviço e o aceite do responsável.
