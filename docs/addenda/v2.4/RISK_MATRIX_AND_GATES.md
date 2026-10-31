# Segurança — autorização de configuração de ONT

## Política de permissões
| Ação | Atendimento | NOC N1 | NOC N2 | ISP Admin | Auditor |
|---|---|---|---|---|---|
| Consultar configuração não sensível | limitado | sim | sim | sim | logs sanitizados |
| Descoberta de capacidades e refresh | leitura | conforme regra | sim | sim | não |
| Alterar SSID / rádio enabled | solicitar | solicitar | executar se policy aprovar | aprovar | não |
| Rotacionar senha Wi-Fi | solicitar | solicitar | executar após aprovação | aprovar | não |
| Canal e Wi-Fi TX power | não | solicitar | executar homologado | aprovar | não |
| LAN DHCP / IP / DNS | não | não | solicitar com plano recuperação | aprovar dupla | não |
| WAN VLAN / PPPoE / NAT | não | não | solicitar com autorização especial | aprovar dupla | não |
| Potência óptica TX/RX | consultar leitura | consultar leitura | consultar leitura | consultar leitura | consultar leitura |

Não conceder poderes por UI sem RBAC/ABAC; conferir tenant e device id vinculados na API, no executor e no Edge. A conta de conexão do GenieACS/USP é escopada e nunca exposta ao browser.

## Escalas de risco default propostas
- **R0** consulta/retrieval (auditar consulta sensível; rate limit).
- **R1** SSID em perfil individual homologado; confirmação + operador autorizado. Política local pode elevar a R2.
- **R2** senha Wi-Fi, canal, largura, Tx power, Guest e reboot; aprovação humana separada em produção conforme política; cuidado com perda de conectividade.
- **R3** LAN IP/DHCP/DNS, WAN PPPoE/VLAN/NAT/IPv6 e firmware; N2 e dupla aprovação, janela e recuperação OOB documentada. Padrão desabilitado até homologação.

## Política determinística do servidor
Preview vinculado a `{tenant,physical_device_id,capability,model,firmware,instance,config_revision,form_schema_version,policy_version,requested_by,expires_at,intent_hash}`. Não aceitar alteração nos parâmetros após aprovação; revalidar firmware/fonte/política no Edge. Device cross-tenant e device não conciliado são `403/409` sem leaking de existência. Controle `nonce` e idempotency-key, lock por escopo Wi-Fi/LAN/WAN mesmo em dual TR-069/TR-369. TTL/replay protection e circuit breaker.

## Dados sensíveis
- Nunca ecoar PSK ou senha PPPoE em tela, diff, log, evento, CSV, prompt LLM, screenshot ou auditoria.
- Novo segredo somente por canal criptografado TLS, persistir de forma cifrada em vault com TTL reduzido; no job apenas `secret_ref`. Apagar após uso ou expiração, registrar hash do intent e efeito **sem valor**.
- `GET /configuration` nunca retorna senha existente, inclusive quando backend possui o valor.
- CSP/cookies seguros/CSRF e autenticação MFA conforme policy; documentação `/ajuda` apenas com fixtures sintéticas.

## Falha e rollback
Antes de modificar LAN/WAN: confirmar canal de acesso alternativo e plano de recuperação. Se sessão TR-069/USP cair após write, não reexecutar às cegas. Marcar `unknown`, explicar e encaminhar runbook de recuperação. Rollback automático só se suportado, exercitado, com janela e confirmação independente.
