# ADR-0053: Teste de conexão pela plataforma para Datacom, Intelbras e Huawei MA5800

Status: **Accepted e construída** | Data: 2026-11-14 | Owner: Claude Code (implementação), Codex (revisão)

Origem: o responsável pediu o teste de conexão pela plataforma nas OLTs reais dos clientes. Hoje a nuvem recusava Telnet (`422 protocol_not_supported`), o catálogo `olt_query` é só Huawei MA5600 R015 e a flag `olt_query` só existia na organização K3G (`409 olt_query_disabled`).

## Decisão
**D1 — O teste é a identidade que o próprio driver já lê.** `olt.connection` (ADR-0041) passa a valer para qualquer OLT estática do Edge com `cloud_id`: Datacom (`show platform`), Intelbras (`card stats` + banner) e Huawei MA5800 (`display version`). O Edge roda a leitura na sessão da coleta, depois dos comandos dela, sob o mesmo arrendamento assinado, guarda de intervalo e orçamento (1 por 15 min, 4 por hora, por OLT). Nenhum comando novo: são os da allowlist exata do driver.

**D2 — Só o teste, nada mais.** Para esses drivers qualquer outra consulta do catálogo termina sozinha como `query_not_enabled` (nada é enviado ao equipamento), e a nuvem recusa antes com `422 vendor_not_supported` quando o fabricante não é Huawei. A flag `olt_query` por organização continua decidindo se o teste é oferecido.

**D3 — Resultado tipado e nulo onde o CLI não informa.** `{product, version, patch, uptime_seconds}`: `patch` e `uptime_seconds` podem ser `null` **só** em `olt.connection` (nunca ausentes); `olt.version` segue estrito. O produto aceita espaço (modelo real "DM4610 HW2"). Modelo ou firmware fora do formato é `bad_output`, nunca aparado nem adivinhado. A tela mostra "não informado".

**D4 — Telnet.** A recusa antiga (Codex r4 do ADR-0046) valia para o cadastro de credencial de OLT gerenciada pela nuvem. O teste não envia credencial nem pede nada operacional ao cadastro: o Edge lê a OLT pela entrada estática dele. A recusa sai do teste; **a entrega de credenciais Telnet pela nuvem continua recusada** (ADR-0046 D3, ADR-0052 D2).

**D5 — Configuração do Edge.** `olt_query_enabled` passa a contar OLT `datacom`, `intelbras` ou `huawei_ma58_r02x` com `cloud_id` (único, minúsculo), além do perfil R015. Continua exigindo `jobs_enabled`, `job_public_key` fixada localmente e `"olt_query"` em `allowed_operations`.

## Riscos
- **R-1:** o teste espera a próxima janela de coleta (até ~18 min), como todo `olt_query`.
- **R-2:** MA5800 após `quit` da coleta: a sessão pode já estar encerrada e a leitura falhar como `session_error`; verificado no uso real (ver runbook).
- **R-3:** a nuvem não conhece o perfil do Edge: uma consulta de catálogo a uma Huawei MA5800 passa pela nuvem e é recusada pelo Edge.

## Provas
`apps/api/tests/test_olt_connection_multivendor.py` (formato do resultado, Datacom/Intelbras/Telnet testáveis, `vendor_not_supported`), `test_olt_center.py` (Telnet não é mais recusado); Edge: `TestConnectionTestOnADriverWithoutTheCatalogReturnsTheIdentityOnly`, `TestConnectionIdentityRefusesWhatTheCloudWouldNotAccept`, `TestConnectionTestOnDatacomIntelbrasAndMA58`.
