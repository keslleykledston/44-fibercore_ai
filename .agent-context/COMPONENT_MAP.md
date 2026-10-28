# Component Map

- `apps/api-core`: FastAPI implementation (bootstrap example currently `starter/apps/api`).
- `agents/edge`: Go binary to run inside ISP environment; *not yet implemented*.
- `apps/web`: Next.js created after Lovable handoff.
- `contracts/`: source of OpenAPI and payload schemas; revision via ADR.
- `configs/modules.yaml`: declarative registry (not live health status).
- `configs/catalog/`: seed identification and intent, writes uncertified.
- `docs/wiki/`: truth for decisions, progress and test evidence.
