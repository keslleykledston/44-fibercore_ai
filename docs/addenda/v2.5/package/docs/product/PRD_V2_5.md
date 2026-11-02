# PRD v2.5 — Descoberta, autorização ONU e Profile Studio

## Personas e objetivos
- Instalador/campo: encontrar ONU descoberta, associar OS/assinante HubSoft, escolher serviço, solicitar autorização.
- NOC N1: acompanhar status, consultar, sinalizar pendências; sem escrita em OLT por padrão.
- NOC N2 / Engenharia: homologar templates, pré-validar, aprovar e executar jobs tipados.
- Admin ISP: governar escopo de OLTs, templates certificados e delegações.
- Auditor: histórico imutável redigido, diffs e evidências.

## Módulo A — ONU Discovery & Activation
- Coleta periódica e sob demanda de ONUs **não autorizadas** por OLT/slot/PON; possuir estados `DISCOVERED`, `STALE`, `ASSOCIATION_REQUIRED`, `READY`, `PENDING_APPROVAL`, `PROVISIONING`, `VERIFYING`, `AUTHORIZED_VERIFIED`, `FAILED`, `UNKNOWN`, `QUARANTINED`.
- Identificadores: tenant, OLT id, chassi/slot/PON, SN, password/LOID apenas quando estritamente necessário e em secret store, timestamp, origem e evidência. Modelo/portas/versão podem ser desconhecidos até registro.
- Prevenir duplicidade SN, autorização paralela, ONT vista em PON diferente, serial já autorizado, conflito com cadastro HubSoft, descoberta antiga, ausência de ordem confirmada ou divergência de modelo/tecnologia.
- Associar ao HubSoft (read-only na fase inicial) por OS/contrato/serial quando disponíveis; não liberar ONU apenas por cadastro positivo, exigir correspondência verificada e decisão humana.
- Selecionar service intent/template certificado ou preencher parâmetros adicionais; preview de diff e risco; job assíncrono; verificação em OLT + opcional GenieACS/USP/BNG.
- Entrada manual de SN/LOID para pré-provisionamento quando `discovery` indisponível: caminho distinto e controle reforçado.

## Módulo B — Service Profile Studio
- Catálogo de templates canônicos versionados e **independentes de fabricante**, com estado `draft`, `tested`, `certified`, `deprecated`; fornecedor-specific renderer em driver OLT por firmware/placa.
- Wizard SIMPLES: (1) serviço Internet bridge/roteada/IPTV/VoIP (se suportado); (2) autenticação PPPoE/IPoE conforme arquitetura, VLAN/hand-off, uplink e portas LAN; (3) plano e controle de banda (perguntar onde limita: BNG, OLT, CPE); (4) hardware/modelo e destinos OLT(s); (5) pré-visualização e salvar versão.
- Modo AVANÇADO sob demanda: DBA upstream, T-CONT, GEM, VLAN translation, QinQ, QoS/traffic tables, OMCI/service profile e restrições vendor-specific.
- PERFIL LÓGICO único pode resultar em entidades físicas distintas (DBA/line/service/traffic/etc.) em cada OLT; inventariar existente, reconciliar config/hash/ID e **reusar sem alterar perfis compartilhados**.
- Deploy em uma ou várias OLTs SOMENTE com preview por alvo, compatibilidade e aprovação por lote (preferir canário 1 OLT), limites de concorrência e backoff.
- Bloquear opções sem capability certificada; dry-run não é execução; distinguir divergências intencionais de drift.

## Catálogo mínimo de intents
1. Internet bridge tagged/untagged Ethernet com service-port/VLAN.
2. Internet PPPoE com handoff bridge para BNG (não forçar PPPoE na ONU).
3. Internet roteada ONT PPPoE/IPoE (somente quando ONT/driver suporta e CPE gestão apropriada).
4. Dados corporativos VLAN/QinQ (prioridade posterior).
5. VoIP / IPTV multicast apenas após homologação dos recursos necessários.

## Aceitação P0
- Fila não-autorizadas para Huawei MA5608T R015 em laboratório, inicialmente fake/fixtures e depois observação real autorizada, sem habilitar auto-find por padrão.
- Um template Bridge+VLAN com compatibilidade validada contra perfil do vendor sem inventar parâmetros de CLI.
- Simular job de autorização com output tipado e estados; mostrar binding com contrato HubSoft quando disponível.
- Bloquear conflito de SN/OLT/PON; read-only para não-homologado; isolamento de tenant e RBAC comprovados; post-check required.
- UI desktop/mobile minimalista; capturas Playwright reais de telas implementadas com dados fictícios, help e changelog.

## Fora de escopo da primeira fase
- Autorizar automaticamente qualquer ONU detectada; manipular perfis em produção; escrever via TR-069 para OLT; substituir perfil compartilhado; mudar uplink/VLAN em massa; firmware de ONT; provisionamento de 1000 ONUs sem canário; interpretar modelo por serial como certeza; CLI arbitrária em produção.
