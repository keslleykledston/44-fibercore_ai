# Roadmap executável (Claude + Codex + Lovable)

## Sprint 0: bootstrap, segurança e contratos — gate inicial

- [ ] Inventário repo, importar legados sem destruí-los, escrever ADRs 1–10.
- [ ] Compose válido, API `/livez` `/readyz` `/modules`, NATS/Postgres, log JSON, migrations.
- [ ] Auth real e tenants com RLS; testes `tenant A`/`tenant B`, endpoint com token real, secrets sem plaintext.
- [ ] Registry de módulos e feature flags; painel status de serviços baseado em dados reais.
- [ ] OpenAPI v2 lint, geração tipos TS/Python, CI lint/test/contract/secret scan.
- [ ] Memory/wiki/ADR+checkpoint obrigatório; Codex PASS.

## Sprint 1: Edge e coleta real (read-only)

- [ ] Edge Go outbound autenticado, configuração local allowlist, heartbeat, cache e replays.
- [ ] GenieACS NBI read-only: devices, projection, last inform, snapshots com staleness.
- [ ] Huawei MA5800 modelo/firmware conhecido fixture -> driver inventário real; testar desconexão sem false offline.
- [ ] ZTE segundo driver read-only em lab/fixture.
- [ ] Sem comandos automáticos de alteração/provisionamento.

## Sprint 2: produto inicial

- [ ] CSV e generic REST ERP, clientes/contratos e associação de evidências.
- [ ] Raio-X FTTH, página ONU 360, busca global e painel NOC.
- [ ] Correlação massiva PON, dedupe e supressão falha Edge.
- [ ] UX-01 a UX-05 com Lovable + testes e Codex.

## Sprint 3: workflows controlados e dual-stack

- [ ] Job state machine, preview, approval, signature, TTL, audit, lock por device/capability.
- [ ] Reboot CPE via GenieACS somente após lab; HTTP 202 tratado queued; pós-check.
- [ ] Interface TR-369, contrato unitário, simulador USP Controller/Agent e PoC OB-USPC (com critérios de segurança/HA/license).
- [ ] Dual-stack conflict tests, update agent canary e version/changelog.

## Sprint 4: comercial / módulos expansíveis

- [ ] SGP/IXC (ou ERP selecionado) mediante acesso real e fixtures redigidas.
- [ ] Driver certificação por firmware, novos templates, OLT read/write lab, provisioning wizard.
- [ ] USP controller em ambiente homologado e testes TR-181/USP, se viável; senão feature flag off.
- [ ] métricas SRE, SLO e hardening, teste restore/chaos, opção K3s se demandado.

## Sprint 5+: inteligência assistida

- [ ] Copiloto read-only com corpus técnico restrito, roteador provider, avaliações e observabilidade.
- [ ] Tool facade sugestão de operação -> humano aprova fora do LLM -> job controlado.
- [ ] Mapa CTO, expansão, relatórios, webhooks, custos por tenant, scale benchmark.

## Definição de pronto (DoD) para cada PR

1. API/schema versionados e testes unitários/contrato.
2. Autorização multitenant e audit de ações/dados onde aplicável.
3. Falha do módulo opcional isolada e estado degradado visível.
4. Edge/device test com fixtures saneadas, sem comandos não certificados.
5. Segurança: lint, dependency scan, secrets scan, threat model para writes.
6. Métricas, logs redigidos, health/ready, timeout, retry e DLQ quando aplicável.
7. Docs de módulo, wiki, ADR, changelog, contexto e limite conhecido atualizados.
8. Codex revisão `PASS` (BLOQUEAR mudanças críticas se `BLOCK`) e Lovable UX review em mudança visual.
9. Testes devem registrar resultado real ou `NOT_RUN` com explicação; nunca alegar sucesso sem execução.

## Ordem de paralelismo

Codex não revisa códigos ainda não finalizados; Lovable pode trabalhar telas usando mocks e contratos versionados em paralelo ao Edge. Claude deve concluir caminhos verticais antes de abrir mais serviços. Sem **merge autônomo de PR crítico** e sem writes em equipamentos sem aceite humano.
