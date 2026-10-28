# ADR-0018 — Correlação de incidentes de PON por quedas recentes, não por proporção de offline

Status: Accepted | Data: 2026-10-28 | Owner: equipe

Relaciona-se a `apps/api/app/api/noc.py` e a `docs/engineering/DRIVER_SDK_INTERFACE.md`.

## Contexto
A regra original abria `pon_mass_outage` quando uma PON **completa** tinha ≥5 ONUs e ≥80% em `offline|los|dying_gasp`. Uma OLT real (Huawei MA5608T, 32 PONs, 775 ONTs) tinha 290 ONTs (37%) offline **de forma crônica** (cadastros antigos). Com `complete=true` a regra abriria incidente permanente e falso em 2 das 32 PONs (`0/0/9`: 33 de 38 offline; `0/1/5`: 5 de 6), sem queda alguma. Por isso o driver dessa OLT foi mantido `identified` (nenhuma PON completa) até esta mudança.

## Decisão
Uma queda em massa é **muitas ONUs caindo juntas**, não muitas ONUs offline.
1. Cada ONU guarda `last_online_at` (último snapshot em que esteve online) e `down_since` (snapshot em que, **vista online**, passou a ser vista down). ONU vista pela primeira vez já down, ou vinda de `unknown`, fica com `down_since = NULL`: **crônica** para a correlação.
2. Queda recente = `down_since` dentro de `DROP_WINDOW` (30 min) antes do `observed_at` do snapshot. Silêncio do Edge não atrapalha: o primeiro snapshot depois do silêncio marca a transição naquele instante.
3. Abertura: população ativa = online + recém-caídas; abre se recém-caídas ≥ `MIN_DROPPED` (5) e ≥ `OPEN_RATIO` (0,8) da população ativa. Crônicas ficam fora do numerador **e** do denominador e aparecem na evidência (`chronic_offline`).
4. Um incidente guarda as ONUs que cobre (`incident_onus`). Ele **resolve quando essas voltam** (`ratio < 0,5`, com evidência suficiente), e não porque a janela de queda expirou. ONUs que caem depois, dentro da janela contada a partir da abertura, entram no incidente.
5. Incidente aberto antes da existência de membros (legado) é julgado pelas ONUs reportadas da PON, como na regra antiga, para não ficar órfão.
6. Primeira observação de uma frota já down não abre nada: sem observação anterior não dá para distinguir queda de frota morta. É o custo consciente; o incidente abre no primeiro snapshot em que ONUs vistas online caem.

## Consequências
- Migration 0012 (`onus.last_online_at/down_since`, `incident_onus` com RLS). Sem exposição nova na API pública.
- A causa (`suspected_cause`) usa os estados das recém-caídas; com um driver que só enxerga `offline` (CLI R015), vira `unknown` até que a causa da queda (SNMP `46.1.24`, `display ont register-info`) seja mapeada para `los`/`dying_gasp`.
- Limiar de 30 min e razão 0,8 seguem sendo heurísticas a ajustar com histórico real; não há SLA implícito.
- Promover um driver a `observed` deixa de criar alarme falso por frota crônica, mas continua exigindo o checklist do SDK (PON vazia, causas de queda).
