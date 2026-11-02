# ADR-0041 — Gestão de OLTs multivendor, base de conhecimento e biblioteca visual (PR0: auditoria e plano)

Status: aceito para execução por PRs pequenos (2026-11-02). Origem: pacote unificado "OLT Fleet Manager + Knowledge Base + Biblioteca Visual Multivendor v2.0" enviado pelo responsável (referência e material de implementação; **não** prova suporte de driver). Nada aqui autoriza configuração em OLT.

## 1. Diagnóstico do que já existe (auditado no repositório em 2026-11-02)
| Área | Hoje | Consequência para o plano |
|---|---|---|
| Cadastro de OLT | **Implícito**: a nuvem cria a linha de `olts` na primeira ingestão do Edge (`apps/api/app/api/inventory.py`); adicionar OLT = editar `olts[]` no `config.json` do Edge (dono). Sem API/UI de cadastro. | O cadastro assistido é novo, mas a credencial continua no Edge. |
| Credencial de OLT | Só no Edge (`secret_file` 0600). A nuvem nunca a recebe. | "Vault credential ref" = rótulo opaco do segredo local do Edge, nunca o segredo (decisão D3). |
| Identidade e nível | `Registry` de firmware no Edge (`agents/edge/internal/olt/driver.go`): Huawei MA5608T R015 `identified`; MA5800 R018 e ZTE C300 só fixtures sintéticas. Nuvem capa em `observed`; `certified` exige homologação. Capacidades por vendor/modelo/firmware em `device_capabilities`. | O "driver resolver" e a matriz L0–L4 devem **reusar** isto, não criar outro. |
| Consultas de leitura | Catálogo `olt_query` (29 consultas, tipado e fechado), `olt.autofind` validado em 2026-11-02. | Teste de conexão = nova operação de leitura nesse mesmo desenho (fail-closed, sem texto cru). |
| Painel MA5608T | `apps/web/src/lib/oltPanel.ts` + `components/OltPanel.tsx` (slots reais, 16 PON por GPFD, LEDs só por prova). Já entregue. | O item "MA5608T interativo" do pacote é **reaproveitamento**, não reescrita. |
| POP | **Não existe** no modelo (FC22-010 aberto). | Associar OLT a POP exige tabela nova (migração reversível, flag). |
| Ativos estáticos web | `apps/web/public` **não existe**; CSP do proxy: `img-src 'self' data: blob:` (serve SVG/PNG locais). | Ativos entram em `apps/web/public/devices/`, sem CDN, sem URL externa. |
| Help Center / capturas | Pipeline e manifesto de capturas existentes (`tests/validate_help.py`, `help-screenshots.spec.ts`). | Cada PR de UI traz how-to + captura real. |
| Flags / RBAC / auditoria | `features`, `permissions.py`, `audit()`, RBAC_MATRIX gerado. | Tudo novo atrás de flag, com permissão própria e linha de auditoria. |

## 2. Auditoria do pacote (dado, não código executado)
Evidência reproduzível: `docs/addenda/v2.6/PACKAGE_AUDIT.md` (saída do `scripts/audit_device_package.py`, com o SHA-256 do zip); os ativos entram no repositório no PR1, onde os testes repetem a verificação.
- Integridade: `SHA256SUMS.txt` 204/204 OK. 69 SVG + 69 PNG; `asset-manifest.json` com 70 entradas = **28 OLT + 41 ONU/ONT + 1 referência** (`olt-huawei-ma5608t-interactive`, sem arquivo próprio: aponta para o painel real já existente). 8 fabricantes (Huawei, Datacom, ZTE, FiberHome, Intelbras, V-SOL, Ubiquiti, Parks). IDs únicos; todos os arquivos existem.
- Segurança dos SVG: varredura de todos (`<script`, handlers `on*=`, `javascript:`, `href` http(s), `<foreignObject`, `<iframe`): **0 suspeitos**. Mesmo assim o registro valida isso em teste a cada mudança.
- Fidelidade: 100 % das OLT estão `schematic_not_model_exact` / `physical_mapping=unverified_from_inventory_required`; as 41 ONU são `generic_form_factor_not_model_exact`. **Nenhum** chassi está verificado. Fotos de fabricantes aparecem só como links de referência (`visual/sources/external-photography.json`): **não** são copiadas.
- Lacunas assumidas pelo próprio pacote: coletores dos novos vendors, perfis/configuração, foto licenciada, homologação por firmware. Nada disso vem pronto.

## 3. Decisões
- **D1 — Imagem ≠ capacidade.** Existir SVG/PNG de um modelo não implica driver, leitura nem escrita. O nível (L0–L4) e o estado vêm do `Registry`/`device_capabilities`; a arte só ilustra.
- **D2 — Três camadas de fidelidade, sempre rotuladas na UI:** `SCHEMATIC` (miniatura genérica por família; todo o pacote), `MODEL_VERIFIED` (geometria validada em laboratório + inventário; hoje só o painel da MA5608T, que é dirigido pelo inventário real e não pelo desenho), `UNKNOWN` (modelo fora do catálogo: fallback por família, sem portas inventadas). **Porta clicável no chassi só com geometria verificada**; nos demais, miniatura + tabela de portas reais/UNKNOWN.
- **D3 — Credencial nunca na nuvem.** O cadastro guarda `credential_ref` (nome opaco do segredo local do Edge) e o Edge resolve; a nuvem não aceita, não guarda e não ecoa senha/chave/IP de OLT em lugar nenhum (nem em log/auditoria).
- **D4 — Somente leitura primeiro; esta ADR não autoriza nenhuma escrita.** Teste de conexão e coletas são leituras do catálogo fechado. Qualquer escrita futura depende de homologação por vendor/modelo/firmware e de emenda formal própria; o ADR-0030 (cujo cabeçalho ainda diz `Proposed`) não é promovido por esta ADR e continua restrito à ONU de bancada. Perfil não homologado: escrita bloqueada; `HOMOLOGATED_WRITES` permanece vazio.
- **D5 — Reuso.** `DeviceAssetRegistry` e resolver novos, mas alimentando o que existe (lista de OLTs, ONU 360°, sidebar, Profile Studio); nenhum módulo de TR-069/TR-369, Profile Studio, descoberta ou Huawei é recriado ou muda de comportamento.
- **D6 — Ativos locais e saneados.** `apps/web/public/devices/{svg,png}`; `<img loading="lazy">` no catálogo; SVG inline só o interativo já existente; qualquer upload futuro de SVG é saneado (lista de permitidos) e fica fora desta ADR.
- **D7 — Flags e reversibilidade.** `device_assets` (biblioteca/catálogo) e `fleet_manager` (cadastro/teste), ambas desligadas por padrão; migrações aditivas e reversíveis; recuo com e2e de flag desligada.

## 4. Plano de PRs (cada um com testes, Codex adversarial, capturas reais e how-to)
| PR | Conteúdo | Banco | Risco |
|---|---|---|---|
| PR0 | Esta ADR + mapa. | — | nenhum |
| PR1 | `DeviceAssetRegistry` (manifesto versionado, resolver puro com fallback por família, busca por fabricante/modelo), ativos em `public/devices`, tela `/rede/catalogo` e miniaturas na lista de OLTs e na identificação da ONU; testes de integridade (IDs, arquivos, SVG seguro, URL local). | nenhum | baixo |
| PR2 | Fleet Manager: tabela `pops`, campos de cadastro da OLT (`pop_id`, `credential_ref`, rótulo), API CRUD com RBAC/auditoria, assistente teste→detectar→confirmar. O **teste de conexão** é uma operação de leitura executada pelo Edge sob os controles abaixo (§4.1). | migração aditiva | médio |
| PR3 | Drivers somente leitura: reforço do Huawei e UM vendor adicional, só com fixture sanitizada de equipamento real de laboratório; sem isso, fica `identified`. | — | médio (depende de hardware) |
| PR4 | Chassi/sidebar: MA5608T já existe; sidebar da ONU/ONT com miniatura por modelo e estado real fora da imagem; demais OLT = miniatura + tabela. | — | baixo |
| PR5 | Base de conhecimento: fontes, comandos de leitura documentados, runbooks, intents e recipes ligados ao Profile Studio (diff, preview, rollback, aprovação por capacidade). | opcional | médio |
| PR6 | Homologação e observabilidade: matriz L0–L4 por modelo+firmware, golden fixtures, alarmes/painéis internos. | — | baixo |

### 4.1 Controles obrigatórios do teste de conexão (condição para iniciar o PR2)
A OLT é frágil e compartilhada com a coleta. O teste **não abre canal próprio**: reusa o canal, a fila, os arrendamentos e os limites do `olt_query` (ADR-0029/0032) e roda **dentro da sessão de coleta** do Edge, com: cache-first (um resultado recente dentro do TTL responde sem tocar a OLT), UMA sessão por vez por OLT (exclusão mútua com coleta e com manobras de bancada), orçamento próprio por OLT (no máximo 1 teste por 15 min e 4 por hora, contado no Edge e na nuvem), cooldown após falha igual ao da coleta, nenhuma repetição automática, resultado tipado fechado (identidade fabricante/modelo/firmware/hardware, nunca texto cru), host key pinada e timeout por comando. O orçamento numérico final é aprovado por escrito **antes** de qualquer linha de execução do PR2. **Aprovado pelo responsável em 2026-11-02** (mensagem do chat: "3. Aprovado", sobre a proposta apresentada): **no máximo 1 teste de conexão por OLT a cada 15 minutos e 4 por hora**, dentro da sessão de coleta do Edge, cache-first, cooldown igual ao da coleta, sem repetição automática; contado no Edge e na nuvem.

## 5. Riscos e como são contidos
1. **Arte vendida como prova** → rótulo `SCHEMATIC` obrigatório em toda superfície; teste que falha se um componente de chassi clicável for montado sem `MODEL_VERIFIED`.
2. **Numeração de portas inventada** → portas só do inventário/driver; sem mapa, tabela com UNKNOWN. O resolver nunca devolve geometria.
3. **Credencial exposta** → D3; teste de que nenhuma resposta/auditoria do cadastro contém segredo/IP (mascarado).
4. **Escrita por acidente** → D4; nenhum PR deste plano adiciona comando de escrita; `HOMOLOGATED_WRITES` continua vazio.
5. **Direitos de imagem** → só os SVG originais do pacote; fotos de fabricantes ficam como link de referência.
6. **Deploy de catálogo** → qualquer mudança no catálogo `olt_query` exige trocar API e Edge juntos (aprendizado de 2026-11-02).

## 6. Fora de escopo agora
Coletores dos novos vendors sem equipamento de laboratório; configuração/provisionamento em qualquer OLT; fotografia licenciada; geometria verificada de qualquer chassi além da MA5608T.

## 7. Rollback
Cada PR atrás de flag; desligar a flag remove telas e atalhos (404). Migrações do PR2 são aditivas e reversíveis (`DROP` das colunas/tabela novas). Ativos estáticos podem ser removidos sem efeito nas funções existentes (o resolver cai no fallback por família).
