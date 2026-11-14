# ADR-0052: Drivers multi-fabricante, Telnet opt-in e `enable` da Huawei

Status: **Accepted e construída** (Edge) | Data: 2026-11-14 | Owner: Claude Code (implementação), Codex (revisão)

Origem: cadastro de seis organizações com dez OLTs reais (Huawei, Datacom, Intelbras, VSOL) e a ordem do responsável de 2026-11-14 ("construa tudo que precisar", "`enable` na Huawei autorizado"). Até aqui o Edge só lia Huawei e ZTE por SSH. As capturas reais (somente leitura, sanitizadas em `docs/wiki/bench/H1-captura-multivendor-clientes-2026-11-14.md`) mostraram três famílias novas.

## Decisão
**D1 — Um driver por família, mesma disciplina.** `datacom` (DmOS, SSH exec) e `intelbras` (OLT 8820, Telnet) entram como `olt.Driver`: allowlist de comandos por correspondência exata, `ReadOnlySession`, `Budget`, nenhum comando de escrita expresso. Os parsers são *golden* contra capturas reais sanitizadas em `testdata/`. **Todos ficam em `identified`**, nenhum em `observed`: faltam PON paginada e ONU com causa de queda (Datacom) e PON vazia de equipamento vivo (Intelbras). Ninguém declara PON completa sem a prova em banda (rodapé da própria OLT, linhas = declarado).

**D2 — Telnet é opt-in, estático, e só onde o fabricante não deixa alternativa.** A Intelbras 8820 não fala SSH. `"transport": "telnet"` **e** `"allow_telnet": true` na entrada da OLT do `config.json` são obrigatórios; sem eles a OLT é recusada na carga da configuração. O Telnet **vai em texto claro** (usuário, senha e saída): só em rede privada/VPN do cliente. **OLT gerenciada pela nuvem nunca usa Telnet** (a proposta é recusada no Edge); só OLT estática, escrita pelo dono no host. A senha vem de `credentials_file` 0600, nunca da nuvem.

**D3 — Datacom: pager desligado só por um sufixo literal.** `SafeCommand` aceita **uma** vez o sufixo ` | nomore` no fim do comando e nenhum outro pipe (`grep`, redirecionamento etc. seguem negados). Ele só desliga o paginador.

**D4 — Huawei MA5800: `enable` é o único comando de sessão não de leitura aceito.** Em modo usuário o MA5800 R022/R024 não lista ONT. O dono autorizou (2026-11-14) o `enable` (sem senha extra) apenas nesses perfis. Ele muda o prompt de `>` para `#` e **não altera configuração**; nada além dele sai da lista de leitura (`display ...`). A OLT que não entra em `#` falha fechada.

**D5 — Identidade da ONU.** A chave na nuvem é (organização, OLT, serial). A Intelbras mostra só 8 hex do serial e o mesmo valor pode aparecer em duas PONs: quando repetido no mesmo instantâneo, o serial vira `<8 hex>@<pon>`; quando único, fica como a OLT mostra.

**D6 — Dispositivos reais atrás de um IP (`nat_shared_ip`).** O Edge identifica o equipamento físico pelo IP (trava, intervalo e cooldown por equipamento), e recusa duas entradas do mesmo IP. Provedores reais expõem várias OLTs por um IP público com portas diferentes (WA TELECOM e ARAUJO). A entrada declara `"nat_shared_ip": true` e então a **porta entra na identidade**; **todas** as entradas daquele IP (inclusive SNMP) precisam declarar, senão a configuração é recusada (Codex r1, MEDIUM: entrada SNMP no mesmo IP). Só CLI (ssh/telnet), nunca com `last_down`.

**D7 — Achados do primeiro uso real (2026-11-14).** (a) Datacom sem `pon_ports` descobre as PONs (a validação bloqueava); o orçamento de comandos com PONs descobertas passa a cobrir 128 PONs. (b) O modelo da Intelbras vem de texto impresso **antes** do login (`olt8820plus login:`): esse texto agora faz parte do banner. (c) MA5800: porta de placa existente sem ONT responde `Failure: The ONT does not exist` e é PON **vazia, não verificada**; `This board does not exist` segue falha. (d) A chave de host fixada é a que o cliente Go negocia: ECDSA quando existe, senão ED25519/RSA conforme o equipamento (RSA nas duas Huawei).

**D8 — Fora desta decisão.** Escrita em qualquer OLT; SNMP novo; teste de conexão e consulta `olt_query` pela nuvem para fabricantes além da Huawei (a nuvem ainda responde `protocol_not_supported`/catálogo só Huawei: ajuste próprio); VSOL (credencial recusada, driver não escrito); promover qualquer perfil a `observed`.

## Riscos declarados
- **R-1:** Telnet expõe credencial na rede. Mitigação: opt-in por OLT, só estático, uso restrito a rede privada.
- **R-2:** o `enable` abre o modo privilegiado da Huawei. Mitigação: só nos perfis autorizados, allowlist continua só `display`, o resto é negado antes de sair do Edge.
- **R-3:** parsers só com uma captura por família podem errar em formatos não vistos. Mitigação: `identified`, PON nunca `Verified` sem rodapé, falha fechada em saída inesperada.

## Provas
`go vet ./... && go test -race ./...` em `agents/edge`: testes golden por driver (`datacom_test.go`, `intelbras_test.go`, `internal/collector/olt_intelbras_test.go`), `SafeCommand` com e sem ` | nomore`, desambiguação de serial, recusa de Telnet sem `allow_telnet` e em OLT gerenciada.
