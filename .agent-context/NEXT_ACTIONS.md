# Next Actions

Ordem decidida (autonomia concedida pelo usuário; Codex = revisor de tudo que for construído; push autorizado em origin = keslleykledston/44-fibercore_ai via SSH 443):
1. PR 3: mock GenieACS NBI + mock Edge + contrato stream/envelope + estratégia de secrets.
2. PR 4: CI de segurança (SBOM, pip-audit, gitleaks local), backup/restore staging, plano de deploy.
3. Sprint 1: migrations de domínio (edges/olts/pon/onu/cpe), Edge Go read-only + NBI mock, driver Huawei MA5800 (fixture) e ZTE (fixture).
4. Sprint 2: CSV/ERP, associação ONU/cliente, incidentes, API de leitura; UX spec -> Lovable em lote.
5. Sprint 3: job state machine/write gate (sem escrita real), USP adapter com simulador, release center.
6. Sempre: Codex adversarial-review por branch antes de merge ff em main + push.
Campo (não bloqueia): host/versão NBI GenieACS, firmware OLT + contas read-only, ERP, retenção.
