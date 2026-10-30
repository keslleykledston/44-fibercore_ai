# Publicação do frontend — checklist de aceite

**Hostname único:** `fibercore.devops.k3gsolutions.com.br`. **Status:** publicado em `LAB` com TLS em 2026-10-28 atrás do nginx do host (ADR-0016). Itens abaixo ainda abertos bloqueiam `INTERNAL_PILOT`.

- [ ] Infra definida e DNS confirmado em A/AAAA; nenhum IP inventado.
- [ ] Next.js real pronto com `/`, `/ajuda` e fluxo de autenticação funcionando.
- [ ] Core API de produção, no prefixo `/v1`, com middleware de autenticação/autorização/RLS.
- [ ] Caddy/Ingress: `/api/v1` -> `/v1` interno; `/ajuda` -> Next.js; TLS/redirect funcionam.
- [ ] Segredos externos, `DEMO_MODE=false`, sem Swagger/debug/API de métricas públicos.
- [ ] Somente 443 (e 80, se aplicável) aberto ao público; NBI/Mongo/Postgres/NATS restritos.
- [ ] Logs sem credenciais/PII, monitoramento de TLS/latência/5xx, backup e recuperação.
- [ ] Testes E2E Chrome/Firefox/mobile: login, troca tenant, busca, ações negadas, ajuda.
- [ ] A11y WCAG 2.2 AA, performance e revisão de telas Lovable/Codex.
- [ ] Screenshots **reais** em desktop/mobile e how-to de cada fluxo publicado.
- [ ] Plano de canary/rollback testado, e registro de versão, data, SHA e aprovador.

- [ ] `web` com uma única réplica (renovação de sessão coalescida em memória, ADR-0017); escalar só depois de coordenação compartilhada do refresh.

- [ ] MFA obrigatório: cada `isp_admin` cadastra o MFA em **Conta › Segurança da conta**; só então definir `FIBERCORE_MFA_REQUIRED_ROLES=isp_admin` no `.env.prod` e reiniciar a API. Guardar os códigos de recuperação fora do sistema. (Sem fluxo de redefinição ainda: perda de celular + códigos exige intervenção no banco.)
- [ ] MFA recente (ADR-0031): com o MFA ativo para quem aprova jobs, troca papéis e concede acesso à plataforma, definir `FIBERCORE_MFA_RECENT_ENFORCE=true` no `.env.prod` e reiniciar a API. Daí em diante essas ações pedem o código do autenticador de novo se o último foi há mais de 10 min. **Antes de ligar**, confirmar que todo `isp_admin` tem MFA: sem ele a ação é recusada (`mfa_recent_required`).
- [ ] Suporte da plataforma: o acesso é só por delegação (Administração → Papéis e permissões, até 8 h, com motivo). A plataforma marca a conta operadora no host com `fibercore-admin platform-operator --email …`.
- [x] Ensaio de restauração em banco descartável: PASS em 2026-10-29 (ver `docs/operations/RESTORE_REHEARSAL_2026-10-29.md`). Falta: rotina agendada, cópia fora do host, restauração do NATS e guarda da chave do MFA fora do host.
- [x] Backup agendado do LAB: `scripts/backup-scheduled.sh` (cron 03:15; pg_dump -Fc + verificação de restauração em banco descartável + retenção 14; log em `~/fibercore-backups/backup.log`; arquivos 0600). Falta: cópia FORA do host (definir destino) e cifra (`BACKUP_GPG_RECIPIENT`).

