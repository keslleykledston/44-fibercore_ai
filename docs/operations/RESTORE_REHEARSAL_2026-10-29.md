# Ensaio de restauração — 2026-10-29 (LAB)

**Resultado: PASS.** Estado do sistema: LAB (não é produção).

## O que foi feito
1. Backup lógico (`pg_dump`) do banco do LAB, tirado antes do deploy da migração 0014 (estado: revisão 0013).
2. Restauração num PostgreSQL 17 **descartável** (container novo, porta só em loopback, senhas de ensaio), com os papéis `fibercore_app` e `fibercore_worker` criados antes, sem BYPASSRLS.
3. Verificação do restaurado; depois `alembic upgrade head` sobre ele (0013 → 0014), como num upgrade real; container removido.

## Evidência
| Verificação | Resultado |
|---|---|
| Restauração com `ON_ERROR_STOP` | sem erros, ~1 s (banco pequeno) |
| Revisão Alembic | 0013 antes; 0014 depois do upgrade |
| Tabelas | 25 |
| RLS forçado nas tabelas de dados | 19 forçadas, 0 ligadas sem forçar |
| Papel da aplicação | `bypassrls = false` |
| Isolamento: papel da aplicação, SEM contexto de tenant | enxerga 0 tenants e 0 memberships |
| Coluna nova da 0014 | presente |

## Limites
- Banco do LAB é pequeno (1 tenant, 1 usuário): **tempo de restauração e de migração não extrapolam** para volume real.
- Não testado: restauração do NATS/JetStream (os eventos pendentes ficam no outbox do Postgres e são reenviados), nem dos arquivos fora do banco (`.env.prod`, chave do MFA — guardar à parte; sem a chave, o MFA cadastrado não é recuperável).
- Não foi feita subida da API sobre o banco restaurado com login (as senhas reais não são usadas em ensaio).
- Backup e restauração ainda são manuais; sem rotina agendada nem cópia fora do host.
