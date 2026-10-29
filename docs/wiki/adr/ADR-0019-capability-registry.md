# ADR-0019: Capability Registry por perfil (vendor/model/firmware/protocolo/operação)

Status: Proposed (fatia mínima em implementação no PR 35) | Data: 2026-10-29 | Owner: equipe | Origem: adendo v2.2, FC22-002

## Contexto
Hoje a homologação vive em três lugares sem ligação: o `Registry` do Edge (OLT, níveis `identified/observed/certified`), `olts.support_level` no Cloud e o gate global `HOMOLOGATED_WRITES` (vazio) em `jobs.py`. Não há nada para CPE/TR-069/TR-369, nem resposta à pergunta "esta operação neste modelo+firmware é suportada, observada ou certificada?". O adendo exige `unknown` por padrão e bloqueio de escrita em firmware não certificado (AC-005).

## Opções
A) Capacidade por dispositivo (`device_id`): explode em linhas e repete a mesma homologação por unidade. B) **Capacidade por perfil** (vendor, model, firmware, protocolo, operação) resolvida a partir do dispositivo. C) Só arquivo YAML versionado: sem RLS/auditoria, sem consulta por tenant.

## Decisão
Opção B. Tabela `device_capabilities` por tenant (RLS forçada): `vendor, model, firmware, protocol(tr069|tr369|olt), operation, support(supported|unsupported|unknown), certification(identified|observed|certified), verified_at, evidence_ref`; único por perfil+protocolo+operação; CHECKs nos enums; **sem linha = `unknown`/`identified`**. O catálogo de operações é código (`app/core/capabilities.py`), alimentado pelas operações reais de `jobs.OPERATIONS` mais leituras; nome inventado de parâmetro/OID/comando **não** entra. Leitura via `GET /v1/devices/{id}/capabilities` (OLT ou CPE). **Escrita só pelo CLI do dono** (evidência obrigatória) até existir fluxo de aprovação humano para promover certificação. O gate de escrita dos jobs continua sendo o global; ligar o registro ao gate fica para FC22-014/015 e **não** é afirmado agora.

## Consequências
Testes: isolamento A/B, `unknown` padrão, enums, escrita ausente da API. Rollback: `DROP TABLE` (aditiva). Limites: resolução do perfil depende de vendor/model/firmware estarem preenchidos no inventário (CPE hoje traz vendor/model; firmware pode faltar → `unknown`). Flag por tenant: ver ADR-0023.
