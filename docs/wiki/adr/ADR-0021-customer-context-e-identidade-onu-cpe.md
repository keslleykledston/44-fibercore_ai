# ADR-0021: Customer Context / Subscriber 360 e vínculo ONU↔CPE

Status: Proposed | Data: 2026-10-29 | Owner: equipe | Origem: adendo v2.2, FC22-004/005, AC-003

## Contexto
Existem `/v1/onus/{id}` e `/v1/onus/{id}/customer` (dado pessoal só com `customers:read`, auditado), `/v1/customers` e associações ERP↔ONU aprovadas por humano. **Não há vínculo ONU↔CPE**: `cpes.canonical_serial` (CWMP) e `onus.serial` (OLT) são identidades de fontes diferentes, e igualdade de string não é prova (o serial CWMP é uma reivindicação do dispositivo — ver ADR-0017/PR 30).

## Decisão
1. Projeção **calculada na leitura** (sem tabela materializada agora): `GET /v1/customers/{id}/context` agrega ONU(s) aprovadas, OLT/PON, incidente, CPE vinculado e estado de contrato, **cada bloco com `source/observed_at/quality`** (ADR-0020). Nunca é fonte comercial. 2. Dado pessoal segue o mesmo RBAC e **auditoria** de hoje; capturas e logs só sintéticos. 3. Vínculo ONU↔CPE em tabela própria com `evidence`, `confidence` e `confirmed_by`; sugestão automática só como *sugerida*, aprovação humana como nas associações; sem vínculo → bloco CPE `unknown`. 4. Evolui a **mesma** rota/tela ONU 360 (C-13).

## Consequências
Testes: A/B, 403 sem `customers:read`, auditoria registrada, vínculo ausente ≠ erro. Migração aditiva futura para o vínculo (não neste PR).
