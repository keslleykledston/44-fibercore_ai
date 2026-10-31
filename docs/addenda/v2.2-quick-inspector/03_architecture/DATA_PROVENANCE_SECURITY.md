# Proveniência, segurança, privacidade e invariantes

## Identidade
- Identificador canônico interno da ONU é key; serial/MAC só exibido se permitido. Nunca usar serial exposto como chave de tenant.
- Toda consulta passa por tenant ativo autenticado no servidor, com RBAC e RLS; não aceitar tenant_id arbitrário vindo da UI para obter outros dados.
- Para IDs externos a que usuário não tenha acesso, evitar revelar existência ou nome do cliente; tratar 404/403 conforme política existente.

## Fonte da verdade por campo
| Campo | Fonte prevista | Regra |
|---|---|---|
| `pon.status` | OLT via Edge/driver | não derivar do ACS |
| `acs.status` | GenieACS NBI via Edge | não derivar da presença PON |
| `optical.rx_dbm` | OLT ou CPE quando homologado | manter source e instante exatos |
| `device.model` | inventário/identificação validada | usar genérico se não conhecido |
| `visual.leds` | mapeamento de capability homologada | não inferir estado físico sem evidência |
| `association` | base de associação + ERP | confidencial, sujeito a RBAC e confiança |
| `last_seen` | cada fonte | distinguir observed_at, collected_at |

## Semântica
- `online` só para observação atual e proveniente da fonte pertinente. `unknown`, `stale`, `unavailable`, `unsupported` são distintos.
- `RX=0` é valor numérico não equivalente a sem observação; `null` é indisponível.
- Não definir regra universal de sinal crítico por dBm; usar severidade de regras aprovadas/firmware/modelo/tecnologia.
- Dados de cliente somente se `association.confidence=confirmed` e `authorization.canViewCustomer=true`; em conflito não mostrar nome como certo.
- Não tentar reconciliar contrato, alteração de serial, SSID, WAN ou firmware dentro do drawer.

## Proteção contra race conditions
Mudança rápida A -> B -> C: estado visual deve carregar C; resultados atrasados de A/B são descartados. Se houver cache, chave com tenant + id + escopo, invalidação correta e nenhum SSR de tenant cruzado.

## Retenção e logs
Sem registrar dados pessoais, senhas, IPs privados sensíveis ou payload ACS em analytics frontend. Usar logs de aplicação observáveis, com mascaramento existente. Nenhum segredo em fixtures/componente.

## Controle de acesso
Ações remotas só no fluxo já aprovado (permissão, dry-run, autorização, execução, pós-check, auditoria). Este adendo é read-only; o link para investigação não concede permissão nova.
