# Ensaio de restauração completo — 2026-11-03 (LAB)

**Resultado: PASS.** Estado do sistema: LAB (não é produção). Roteiro repetível: `scripts/restore-rehearsal.sh <dump>` (ADR-0041 não depende dele; é gate do piloto interno).

## O que o roteiro faz (tudo num PostgreSQL 17 descartável, porta só em loopback, senhas de ensaio; nada toca o banco do Compose)
1. Confere o SHA-256 do dump (ou decifra o `.gpg` e confere o do claro). Checksum adulterado ⇒ recusa antes de subir qualquer coisa (testado).
2. Cria o container e os papéis `fibercore_app/worker/rbac` (eles não vão no dump) e restaura com `--exit-on-error`.
3. Confere RLS: nenhuma tabela com RLS ligado e não forçado, nenhum papel da aplicação com bypass/superuser, e o papel da aplicação SEM contexto de tenant enxerga 0 linhas de tenants/memberships.
4. Roda `alembic upgrade head` sobre o restaurado e compara com o head do código (no-op se o dump já está no head; senão é ensaio real do upgrade).
5. **Sobe a API sobre o banco restaurado**, cria um usuário de ensaio SÓ nesse banco, faz login, lê `/v1/olts` (contagem igual à do banco) e prova que um workspace alheio dá 404.
6. Roda a varredura do sweeper com o papel do worker.
7. Remove o container e os temporários (também em caso de falha).

## Evidência (dumps reais da LAB, 1 tenant)
| Verificação | Dump `…T012753Z` (head 0046) | Dump `…T042335Z` (head 0047) |
|---|---|---|
| Restauração | sem erros, 1,9 s | sem erros, 1,9 s |
| Upgrade `alembic` | **0046 → 0047 aplicado sobre dados reais**, sem erro | no-op |
| RLS | 49 forçadas, 0 ligadas sem forçar, 0 papéis com bypass | idem |
| Papel da app sem contexto | 0 linhas | 0 linhas |
| API sobre o restaurado | `/readyz` 200; login; OLTs pela API = 1 = banco; workspace alheio 404 | idem |
| Sweeper (papel do worker) | `0/0/0` | `0/0/0` |
| Volume restaurado | 775 ONUs, 9 CPEs, 53 jobs, 896 auditorias, 631 eventos | idem |

## Fecha do ensaio de 2026-10-29
O limite "não foi feita subida da API sobre o banco restaurado com login" deixa de valer: a API sobe e lê, e o upgrade de migração é exercitado sobre cópia de dados reais antes de ir para a LAB.

## Limites (continuam valendo)
- Banco pequeno (1 tenant): tempo de restauração e de migração **não extrapolam** para volume real.
- As chaves do ensaio são descartáveis: o que está cifrado com a chave real (MFA cadastrado) não é lido aqui. Sem a chave real guardada à parte (`MFA_ENCRYPTION_KEY`, `.env.prod`), o MFA não é recuperável: **a guarda dessa chave segue com o responsável**.
- NATS/JetStream não é restaurado (os eventos pendentes ficam no outbox do Postgres e são reenviados com `relay replay`).
- O backup segue manual/agendado no host, sem cópia fora do host e sem cifra por padrão (`BACKUP_GPG_RECIPIENT` ainda não definido): item de infra do responsável.
- O Edge e seus arquivos locais (credenciais de OLT, cache SQLite) não fazem parte do dump.
