# PRD integrado — OLT Provisioning, Profile Studio e Expert Profile Editor

## Problema
ISPs mantêm profiles legados distribuídos em OLTs multivendor. Instalar ONU exige identificar PON e serviço, escolher DBA/LINE/SERVICE/VLAN/T-CONT/GEM e evitar perfis incompatíveis. Configuração manual em CLI é repetitiva, não auditável e propensa a alterar serviços compartilhados. O FiberCore deve entregar UX simples para N1/campo e editor avançado controlado para engenheiros N3.

## Personas e permissões
- **Instalador/Campo:** ler fila de ONUs, localizar OS/cliente, selecionar template certificado e solicitar autorização; não cria profiles físicos nem executa CLI.
- **NOC N1:** diagnosticar e acompanhar; somente leitura por padrão.
- **NOC N2:** pré-validar, pré-visualizar, acompanhar jobs e aprovar apenas conforme política.
- **Engenheiro N3:** importar profiles, editar template canônico em formulário/YAML/JSON tipado, criar variante/versionar, investigar drift, propor migração; não ganha bypass do motor de aprovação.
- **Revisor distinto:** aprovar plano específico pelo hash e risco, respeitando maker-checker.
- **Auditor:** timeline e evidências sanitizadas, sem segredos.

## Módulo A — ONU Discovery & Authorization
1. Observar ONUs sem autorização por OLT/slot/PON, SN (quando reportado), origem e horário; suportar `UNKNOWN` e `STALE`.
2. Deduplicar sem confundir descoberta em OLT diversa com mesma identidade física; bloquear serial conflitante, mudança de PON, ONT já autorizada e coleta velha.
3. Integração HubSoft read-only para associar cliente/contrato/OS/serial, se dado disponível. Desconexão ERP nunca produz associação inventada nem autoriza automaticamente.
4. Operador seleciona template certificado; pré-validação técnica / localidade / VLAN / ONT; preview e aprovação; job assíncrono Edge → driver OLT → readback.
5. Confirmação pós-provisionamento separa `AUTHORIZATION_OK` de `SERVICE_VERIFIED` e `CPE_ONLINE` (não obrigatoriamente imediatos).

## Módulo B — Wizard assistido
1. Escolher cenário Internet bridge / roteada ONT / dados corporativos / IPTV / VoIP, conforme capability comprovada.
2. Definir VLAN, tagged/untagged/translation, serviço, porta LAN, PPPoE no BNG ou CPE, velocidade referencial e ponto real da limitação (BNG/OLT/CPE).
3. Selecionar modelos de ONT, tecnologia PON, OLTs/versões de firmware.
4. Mostrar validações e profiles existentes equivalentes; preview por OLT e alocação local de IDs apenas na fase preparada.
5. Salvar service intent versionado, que não efetua alterações na OLT por si só.

## Módulo C — Modo Especialista
1. Abrir `Rede → Profiles → [template] → Modo Especialista` ou `Rede → OLTs → [OLT] → Profiles existentes → Importar`.
2. **Inventário e importação read-only:** snapshot nativo (sanitizado), provenance, fingerprint, referências reais (ou desconhecidas), status de coleta e campos não observáveis.
3. **Comparador:** comparar contra template existente, outra revisão ou profile da OLT; normalizar tipos, unidades e semântica por driver; marcar EQUAL/CHANGE/ADD/REMOVE/NOT_OBSERVABLE/UNSUPPORTED/CONFLICT.
4. **Editor avançado:** clone draft, formulário de DBA, T-CONT/GEM, VLAN/QinQ, QoS, ONU port capabilities, IGMP/VoIP somente suportados; alternância YAML/JSON canônico, schema por firmware; validação on change + backend. Texto CLI existente só referência não executável, comandos previstos somente leitura opcional.
5. **Resolução de bindings:** `reuse_exact` para profile equivalente e fresco; `adopt_reference` para mapear objeto preexistente com evidência; `clone_new_revision` para novo profile; `plan_migration` é solicitação separada por ONUs explicitamente selecionadas; `blocked` quando dados insuficientes/conflitantes.
6. **Versionamento:** rascunho mutável com ETag, revisão publicada imutável com diff/changelog/autor. Publicar no catálogo **não envia configurações** à OLT.
7. **Planejar execução:** preview com intended changes/impacts/per-target, referências, dependências, IDs, TTL, fingerprint, risco e hash; canário antes de lote, sem transação global falsa; logs e pós-readback independente.

## Regras de produto
- Não incluir um segundo ACS, segundo executor ou um backend paralelo. Perfis OLT ≠ configuração WAN/Wi-Fi ONT.
- Um template lógico pode ter bindings físicos específicos e IDs diferentes em cada OLT, mesmo dentro do mesmo fabricante.
- Não editar in-place profile em uso (inclusive referência contada 0 por política conservadora inicial). Clone + migração aprovada; se referência desconhecida, bloqueio.
- Não inferir segurança de comparações apenas por nome/ID/texto; comparação precisa ser semântica, com campos não observados bloqueando equivalência.
- Sem escrita quando driver não tem certificação exata vendor/model/firmware/card/feature/operation.
- Comando arbitrário do navegador/LLM não vira ação na OLT; parâmetros vendor-specific são declarativos e allowlisted.
- LGPD: tenant scoping em tudo, redigir LOID/SN sensível em telas de baixo privilégio e nenhum credential secret em audit ou screenshot.

## Primeira entrega do piloto
Huawei MA5608T na versão e placa GPON reais **a confirmar no laboratório**, primeira operação read-only. Entregar fluxo com fixtures de descoberta + snapshot de profile + template Internet Bridge + comparação + clone + diff + dry-run. Só homologação posterior poderá ativar escrita.

## Critérios de aceitação
- N1 encontra ONU nova e entende `última coleta` sem saber CLI.
- N3 importa profile real sem escrever, compara com template e cria variante; alteração não muda profile original nem impacta ONUs referenciadas.
- Em OLTs A/B, mesmo template pode resolver reuse em A e clone em B; diffs e hashes independentes, sem IDs globais.
- Estado `UNKNOWN`/`STALE`, incompatibilidade/impacto não verificado e alteração simultânea falham fechado.
- Auditoria de plano aprovada com identificação de autor/aprovador e readback; evidência real antes de marcar VERIFIED.
- Docs e capturas Playwright da UI implementada no mesmo PR.
