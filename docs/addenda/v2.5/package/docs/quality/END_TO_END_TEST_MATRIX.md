# Matriz de testes de aceite — implementar no repositório

| Cenário | Resultado esperado | Teste |
|---|---|---|
| Serial em duas PONs ou já autorizado | conflito, bloqueia preview | integração |
| HubSoft inoperante | read-only continua; escrita depende de associação comprovada/política | integração |
| Mesmo nome native profile com hash diferente | CONFLICT, não sobrescreve | unit/integration |
| Profile usado por 126 ONUs | clone-only, nunca in-place | unit/integration |
| Reference count `null` | migrar bloqueado | unit |
| Snapshot stale ou firmware mudou | approval/preview invalidado | unit/e2e |
| Mapeamento GPON aplicado a XGS-PON | capability bloqueia | unit |
| DBA 500 Mb vs plano 500 Mb no BNG | não converter implicitamente | unit |
| YAML/JSON contém `raw_cli` ou segredo | reject 422, auditar | API |
| ETag divergente em PATCH | 409/412, sem perda de edição | API |
| Tenant B acessar snapshot da OLT A | 403/404 e RLS efetivo | integration |
| Plano aprovado e alterado antes da execução | hash mismatch, abortar | integration |
| Criar profile já existente semanticamente igual | reuse no-op | unit |
| Falha após 1/3 etapas na OLT | PARTIAL, sem repetir comandos cegamente | fake driver |
| Executor recebe aprovação ausente | bloqueio no Edge | contract |
| Preview para 3 OLTs, uma incompatível | plano separado por OLT, alvo incompatível bloqueado | integration |
| Login N1 | nenhuma opção avançada ou write ativo | Playwright/accessibility |
| N3 importa e clona perfil legado | snapshot inalterado e diff visível | Playwright |
| Ajuda/screenshots | artigos e PNG reais no PR, sem segredos | CI |

**LAB:** para Huawei MA5608T, coletar `display version`, card/slot/version, modo PON e capacidade driver; certificar comando de leitura, criação de profile, registro, serviço e readback, cada um separadamente. Scripts sintéticos anexos **não** substituem homologação. Não configurar VLAN uplink/DBA/serviço com exemplos copiados sem validação do ambiente.
