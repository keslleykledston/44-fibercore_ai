# ADR-UX-DEPLOY-001 — Endereço público oficial, TLS e roteamento

**Decisão aprovada no escopo do produto:** frontend público **`https://fibercore.devops.k3gsolutions.com.br`**.

## Contrato de URLs

| Superfície | URL pública prevista | Requisito |
|---|---|---|
| Aplicação frontend | `https://fibercore.devops.k3gsolutions.com.br/` | Next.js, login, UI multitenant |
| Central de Ajuda | `https://fibercore.devops.k3gsolutions.com.br/ajuda` | Guia contextual autenticado e busca |
| API do produto | `https://fibercore.devops.k3gsolutions.com.br/api/v1` | Mesmo origin, validação de sessão/token e escopo |
| Docs API (se habilitados) | **restrito ao ambiente interno** | Não publicar Swagger/debug automaticamente |
| GenieACS NBI (7557), Mongo, NATS, DB, Edge gateway administrativo | **não públicos** | acesso privado, mTLS/ACL/roles específicas |

A configuração canônica está em `configs/deployment/public-domain.yaml`. Não construir links baseados em IP ou hostname de desenvolvimento; o cliente web usa caminhos relativos. `contracts/fibercore-v2.openapi.yaml` usa `servers: [{url: /api/v1}]`. O proxy deve **remover somente o prefixo `/api`**, mantendo `/v1/*` na aplicação interna. Verificar esse mapeamento por teste E2E antes do deploy.

## Topologia escolhida

Internet (HTTPS 443) -> proxy Caddy/Ingress -> frontend Next.js -> API FastAPI (rede privada) -> módulos internos. A rota `/api/v1/*` vai ao `api-core:8000/v1/*` com o prefixo `/api` removido. O frontend serve `/ajuda` através de uma rota Next.js; documentos de engenharia e agentes não serão expostos como arquivos públicos.

### Configuração de infraestrutura pendente (não presumir realizada)

1. DNS A e/ou AAAA para o IP público do ingress/LB correto (não adivinhar endereço); verificar propagação.
2. Liberação de 443/TCP e, se necessário para ACME HTTP-01 e redirect, 80/TCP; preferir DNS-01 se a política de rede exigir. Revisar IPv6 se houver AAAA.
3. Certificado TLS válido, renovação automática e SNI correto para o hostname; realizar teste de renovação e expiração.
4. Configurar proxy conforme `infra/deploy/Caddyfile.example`; manter volumes/certificados persistentes, limites, rate limit na API, headers de segurança e logs sanitizados.
5. Não expor aplicação demonstrativa (`DEMO_MODE=true`) à internet. Somente ativar publicação após autenticação real, RLS e revisão Codex PASS.
6. Backups, observabilidade, healthchecks, alertas e caminho de rollback comprovados. Não afirmar alta disponibilidade usando um host Compose.
7. Validar `https://fibercore.devops.k3gsolutions.com.br/`, redirecionamento HTTP/HTTPS, `.../ajuda`, autenticação, tenant isolation e `.../api/v1` via testes reais; registrar screenshots e evidências sem segredos.
8. Em K3s, usar Ingress/Traefik (ou gateway adotado em ADR), TLS e readiness, mantendo o mesmo hostname e caminhos; não depender de IP interno na UI.

### Segurança de publicação

Somente proxy é publicável; serviços `postgres`, `nats`, `genieacs-nbi`, `usp-adapter` e Mongo não podem receber portas públicas. CORS preferencialmente não necessário para browser same-origin. `Secure`, `HttpOnly`, `SameSite` em cookies, CSRF quando aplicável, CSP testada (sem quebrar o frontend), TLS e MFA para perfis privilegiados. HSTS somente após homologação do TLS em produção.

**Estado atual:** definição documental; não confirma DNS, certificado, implantação ou site operacional. Evidências deverão ser registradas em `docs/wiki/TEST_EVIDENCE.md`.
