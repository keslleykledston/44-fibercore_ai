# Segurança, LGPD e operações supervisionadas

## Mandamentos

1. `read-only` como padrão técnico e de UI; falha de autenticação/autorização = deny.
2. Usuário pertence a um ou mais tenants com papéis e escopo por objeto; service accounts próprias, tokens curtos, MFA para admins, ações de alto risco e suporte break-glass.
3. `tenant_id` não é inferido exclusivamente de header fornecido pelo cliente. Validar identidade, membership e permissão no backend; RLS PostgreSQL com roles sem BYPASSRLS/superuser e `SET LOCAL app.tenant_id` validado em transação; não confiar só no RLS.
4. K3G suporte só com delegated access temporário, aprovação do ISP conforme política, reason e audit trail.
5. Cloud não expõe CWMP/NBI, SSH, SNMP nem MQTT administrativamente para usuários comuns. Edge recebe apenas operações tipadas e allowlisted, protegidas por envelope autenticado.
6. Segredos via secret manager ou arquivos Docker secrets com permissão; nunca em README, prompts, AI, wiki, logs ou changelog. Prefixos de código e serializers redigem senha, PSK, token, PPPoE password, private key e PII sensível.

## Perfil de papéis

| Papel | Listar estado | CSV/ERP | Ler Wi-Fi | Reboot | Provisionar | Releases |
|---|---|---|---|---|---|---|
| ISP Admin | sim | sim | sim | autorizar | aprovar | aprovar tenant |
| NOC N2 | sim | conforme escopo | sim | solicitar | solicitar | não |
| NOC N1 | sim | leitura limitada | sem PSK | solicitar sob política | não | não |
| Atendimento | leitura limitada | leitura limitada | SSID, sem PSK | não | não | não |
| Auditor | auditoria mascarada | não | não | não | não | ler histórico |
| Platform Admin | suporte delegável | não por padrão | não | não por padrão | não | publicar sistema |

## Risco de ação

- **R0** read/list/refresh seguro; sem aprovação, rate limit e auditoria de acesso.
- **R1** reboot individual; operador com permissão e confirmação, janela e verificação.
- **R2** alteração SSID/PSK, plano, provisionamento individual; aprovação explícita (preferência aprovador distinto).
- **R3** firmware, exclusão, bulk, impacto OLT/PON; dupla aprovação, manutenção, backup quando suportado e checklist; desabilitado em piloto.

A política pode elevar risco por quantidade de clientes afetados, VIP, horário, estado do NOC e falta de rollback.

## Job gate

Estados: `DRAFT -> PREVIEWED -> PENDING_APPROVAL -> APPROVED -> DISPATCHED -> ACCEPTED -> DEVICE_PENDING -> VERIFYING -> SUCCEEDED|FAILED|EXPIRED|UNKNOWN|CANCELLED`. `SUCCEEDED` exige pós-check. Uma aprovação cobre `tenant`, alvo, versão de comando, argumentos redigidos/hash, janela e expiração, não um comando genérico futuro.

## Defesas adicionais

- mTLS Cloud/Edge, rotação automática de identidades, revogação, allowlist de NBI e OLT no Edge, TLS entre contêineres em produção onde aplicável, outbound domain allowlist.
- SSRF: URL ACS/USP não é aceita arbitrariamente de usuário; Edge valida IP/máscara e limita conexão a hosts definidos localmente.
- Supply chain: dependency pin, Renovate/Dependabot PR, SAST/SCA, SBOM, assinatura images/packages, drivers assinados, review obrigatório.
- Event bus: autenticação, subjects por tenant, ACL por serviço, TTL e schemas versionados, payload sensível minimizado.
- LLM: retrieval apenas por tenant, filtros de nível de classificação, ferramentas read-only, anti prompt-injection, sem prompt contendo segredos; outputs são sugestões verificáveis e não evidência.
- LGPD: contratos/DPA, base legal por operação, minimização, retenção, logs de acesso a CPF/telefone/endereço, pseudonimização para métricas, processamento em região aprovada.

## Testes obrigatórios

Tenant A busca Tenant B = 403/404 sem existência revelada; admin de plataforma sem delegação não acessa dado cliente; replay nonce/job rejeitado; transição de estados ilegal rejeitada; request com OLT IP fora allowlist negada; PSK em logs/webhooks ausente; import CSV malicioso validado; CPE dual-stack só uma alteração simultânea.
