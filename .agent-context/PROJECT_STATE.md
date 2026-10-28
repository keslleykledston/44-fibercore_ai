# Project State — FiberCore AI

- As of 2026-10-27: planning/build kit delivered. No real device collection or production system implemented by this package.
- Chosen stack: FastAPI+PostgreSQL+NATS+Go Edge+Next.js; Compose dev and K3s HA later.
- GenieACS TR-069 pre-existing in ISP site; must access NBI only via authorized private Edge.
- USP TR-369 requires separate controller; candidate lab OB-USPC, production not decided.
- Current priority: Sprint 0 secure foundation (auth/tenants/RLS/CI/module registry), then Edge and read-only NBI.
- Review route: Claude implements, Codex review gate, Lovable UX handoff; wiki and evidence each PR.
- Read `README_START_HERE.md` and `docs/product/ROADMAP_BACKLOG.md` for next steps.
