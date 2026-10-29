# ADR-0021: Customer Context / Subscriber 360 e vínculo ONU↔CPE

Status: Accepted (2026-10-29, aprovado pelo responsável; implementação em PR 37/38) | Data: 2026-10-29 | Owner: equipe | Origem: adendo v2.2, FC22-004/005, AC-003

## Contexto
Existem `/v1/onus/{id}` e `/v1/onus/{id}/customer` (dado pessoal só com `customers:read`, auditado), `/v1/customers` e associações ERP↔ONU aprovadas por humano. **Não há vínculo ONU↔CPE**: `cpes.canonical_serial` (CWMP) e `onus.serial` (OLT) são identidades de fontes diferentes, e igualdade de string não é prova (o serial CWMP é uma reivindicação do dispositivo — ver ADR-0017/PR 30).

## Decisão
1. Projeção **calculada na leitura** (sem tabela materializada agora): `GET /v1/customers/{id}/context` agrega ONU(s) aprovadas, OLT/PON, incidente, CPE vinculado e estado de contrato, **cada bloco com `source/observed_at/quality`** (ADR-0020). Nunca é fonte comercial. 2. Dado pessoal segue o mesmo RBAC e **auditoria** de hoje; capturas e logs só sintéticos. 3. Vínculo ONU↔CPE em tabela própria com `evidence`, `confidence` e `confirmed_by`; sugestão automática só como *sugerida*, aprovação humana como nas associações; sem vínculo → bloco CPE `unknown`. 4. Evolui a **mesma** rota/tela ONU 360 (C-13).

## Consequências
Testes: A/B, 403 sem `customers:read`, auditoria registrada, vínculo ausente ≠ erro. Migração aditiva futura para o vínculo (não neste PR).

## Nota de implementação (PR 37, 2026-10-29)
- Vínculo em `onu_cpe_links` (migration 0017); o campo é `reviewed_by/reviewed_at` (não `confirmed_by`) porque rejeitar também é uma revisão humana. `CHECK`: sugestão não tem revisor.
- Regra única hoje: `serial_equal` (confiança 0.50; 0.20 e **não confirmável** se o serial da ONU existe em mais de uma OLT). Igualdade de serial é indício, nunca prova.
- Um vínculo confirmado por ONU e por CPE (índices únicos parciais); rejeitado não é re-sugerido.
- O contexto só considera ONUs de associação **aprovada**; sem ONU aprovada ⇒ `unknown` (não se afirma nada). Incidente exige `incidents:read`, senão `incident_hidden`.
- **Suposição a aprovar:** dado de ERP é "atualizado" por 7 dias (importação em lote, não telemetria).
- Flags `onu_cpe_links` e `customer_context` nascem **desligadas** (ADR-0023); ligadas só no tenant demo pelo seed.
- `evidence.rule` é obrigatório no banco (CHECK; `IS TRUE` porque `NULL` passaria num CHECK simples): nenhum vínculo existe sem a regra que o produziu. A confirmação humana é registrada (`reviewed_by/at`, auditoria, evento); justificativa em texto livre fica fora desta fatia.
- As duas flags são **independentes**: `onu_cpe_links` governa o bloco `cpe` (ONU 360 e contexto); `customer_context` governa só a rota do cliente (dado pessoal). Testado.
- Ambiguidade é contada com a **mesma normalização** da regra (`upper(btrim(serial))`); o contexto devolve no máximo 50 ONUs (`onus_truncated`; truncado nunca é `complete`).
- Isolamento: as consultas filtram por id e a barreira é a RLS forçada de cada relação lida (teste lê `pg_class`/`pg_policies` de todas).

