# ADR-0033: ERP Hub — HubSoft primeiro (P0), IXC (P1) e SGP (P2) adiados

Status: Accepted (HS-01 e HS-02 implementados contra mocks) | Data: 2026-10-31 | Owner: equipe | Origem: decisão de produto do responsável (adendo v2.3.1 "HubSoft primeiro"). Não é autorização para refatorar outros módulos nem para testar em ERP de produção.

## GAP (repo em 2026-10-31 × adendo v2.3.1)
| Item do adendo | Estado no repo | Ação |
|---|---|---|
| Registro de provedores (HubSoft P0, IXC P1, SGP P2) | Havia só a lista `planned` em `docs/erp/ERP_INTEGRATIONS.md` | `app/core/erp_hub.py` (HS-01) |
| Conexão por provedor, vários por ISP, referência de segredo | Não existia; só importação CSV (`/v1/erp/import-csv`), `customers` e `associations` | Tabela `erp_connections` (migração 0030, RLS forçada) e `/v1/integrations/erp*` |
| Cofre de segredos | Não existia | Arquivo 0600 por tenant em `ERP_SECRETS_DIR/<tenant_id>/<ref>.json`; o banco guarda só o nome |
| OAuth HubSoft com cache | Não existia | `app/integrations/hubsoft.py` (HS-02) |
| Lookup de cliente (`GET /api/v1/integracao/cliente`), normalização, vínculo, UI, ensaio real | Não existem | HS-03 a HS-06: **não iniciados** |
| Observabilidade da conexão | Estado e último erro por conexão; sem métricas | HS-07 depois |
| IXC/SGP | Sem código | Ficam no registro com `real_connector=False`: a conexão não pode ser criada, testada nem ligada |
Não há código HubSoft anterior a sobrescrever. A sprint em curso (captura da OLT, ADR-0032) segue sem mudança.

## Decisões
1. **Ordem de homologação:** HubSoft → IXC → SGP. Os alicerces (tabelas, RLS, registro, jobs) são agnósticos de fornecedor; IXC/SGP mantêm contratos e mocks, sem endpoint real.
2. **Somente leitura, sempre.** Nenhum endpoint escreve no ERP; bloqueio/desbloqueio, financeiro, PHY_ADDR, PPPoE e provisão estão fora de escopo.
3. **Flag por tenant `erp_hubsoft`** (desligada por padrão). Com ela desligada nada é criado, testado nem ligado; só `disable` funciona (chave de emergência).
4. **Permissões:** `erp:manage` (cadastrar/ligar/desligar; R3) e `erp:test` (testar e listar; R2), ambas só do `isp_admin`. Nenhuma ação de ERP cria, aprova ou suspende comando em OLT.
5. **Segredo por referência.** A conexão guarda `secret_ref` (`^[a-z0-9][a-z0-9._-]{2,63}$`). O arquivo precisa ser regular, sem symlink, sem acesso de grupo/outros, com exatamente `client_id`, `client_secret`, `username`, `password`. Um tenant só alcança o próprio diretório. A versão (hash do arquivo) entra na chave do cache: segredo rotacionado = token novo. Nenhum segredo, token ou corpo de resposta vai a resposta de API, log, auditoria ou erro.
6. **Guarda de URL/SSRF.** Só `https://<nome DNS>` na porta padrão, sem usuário, caminho ou query, e **na lista do operador** (`ERP_ALLOWED_HOSTS`, exato ou `*.sufixo`; vazia = nada permitido). A lista é reconferida a cada uso. O nome é resolvido a cada teste: se QUALQUER resposta não for endereço público global, o nome inteiro é recusado; a conexão é feita no endereço verificado (SNI e Host pelo nome, TLS valida o nome), então a checagem e o uso veem o mesmo endereço (sem rebinding). Redirecionamentos nunca são seguidos; corpo limitado a 1 MiB.
7. **Política do token (HS-02):** `POST /oauth/token` (`grant_type=password`), cache por `(tenant, conexão, host, versão do segredo)` até `expires_in` menos margem de 30 s; uma autenticação compartilhada por conexão (trava); **401 em consulta → descarta o token e autentica UMA vez**; 401/403 na autenticação são finais; **429** espera o `retry_after` (cabeçalho ou corpo) só se ≤ 5 s e uma única vez, senão devolve `RATE_LIMITED` com o valor; 5xx/rede: até 2 novas tentativas com jitter; prazo total de 20 s. Limites próprios, mais conservadores que o publicado (por IP: auth 30/min, demais 20/s): 6 autenticações/min (rajada 3) e 2 consultas/s (rajada 4) por conexão, e um teste de conexão a cada 10 s.
8. **Modo `lookup_only`** é o único aceito. Sincronização total/incremental só depois de comprovar listagem paginada ou incremental numa instância autorizada.
9. **Estados:** `unconfigured → healthy | degraded | unauthorized | rate_limited | offline | disabled`; a saúde da integração não é a saúde do assinante e a falha do ERP não afeta OLT/GenieACS/Edge.
10. **Não é homologado.** Tudo aqui foi exercitado só com mocks. `integration_status` nunca vale "homologated" no código; `READ_HOMOLOGATED` por endpoint/versão será um fato registrado após ensaio real autorizado (checklist `14_HUBSOFT_HOMOLOGATION_CHECKLIST`).

## Consequências
- O teste de conexão faz apenas a autenticação. A consulta de cliente (`busca`, `termo_busca`) só entra em HS-03, com os valores confirmados na instância autorizada.
- Cache do token é por processo da API; com vários processos cada um autentica uma vez (dentro do limite próprio). Cache compartilhado fica para quando houver mais de um processo em produção.
- O dono precisa criar o arquivo de segredo no servidor e preencher `ERP_ALLOWED_HOSTS` antes de qualquer teste; nada é pedido em chat.
- Transporte `edge` (ERP em rede privada) é reservado e recusado até ter entrega própria.

## Alternativas descartadas
Guardar o segredo cifrado no banco (a chave e o dado ficariam no mesmo sistema; o arquivo por tenant dá a mesma garantia sem nova superfície); aceitar qualquer URL https (SSRF); cache de token global (vazaria entre tenants); homologar IXC/SGP em paralelo (decisão de produto).
