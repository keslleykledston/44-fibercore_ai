# Component Map
- `apps/api/app/core/{settings,db,security,modules}.py` — config, conexão com contexto RLS, JWT/Argon2, registry+probes.
- `apps/api/app/api/{deps,routes}.py` — auth/tenant resolution, endpoints.
- `apps/api/app/cli.py` — provisionamento (role dona).
- `apps/api/alembic/versions/0001_*.py` — schema+RLS+grants.
- `configs/modules.yaml` — manifest; `contracts/fibercore-v2.openapi.yaml` — contrato.
- `infra/compose/compose.yaml`, `Makefile`, `.github/workflows/ci.yml`.
