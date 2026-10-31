# Speed Diagnostics (TR-143) — guia de homologação

Âmbito: **somente a ONT de bancada**, com autorização prévia de uso único do responsável (ADR-0030, emenda e ADR-0038). Nada aqui autoriza teste em ONT de cliente, em produção ou em horário de pico. **Este guia não contém evidência simulada:** as planilhas abaixo começam vazias e só se preenchem com o que foi observado em uma execução real autorizada.

## 0. O que precisa existir antes (só o responsável resolve)

| # | Pré-requisito | Quem | Estado |
|---|---|---|---|
| 1 | Autorizar a homologação na ONT de bancada e aprovar a emenda ao ADR-0030 | responsável | pendente |
| 2 | Nó de teste do provedor (Core e, se houver, Internet): `GET /health` (200, corpo `ok`), `GET /dl/<perfil>`, `PUT /ul/<perfil>`, **sem redirecionar nunca**; capacidade validada | responsável / rede | pendente |
| 3 | ACL/firewall de saída da WAN de serviço da bancada permitindo só os nós de teste (ou a prova do item 7 abaixo) | rede | pendente |
| 4 | Qual é a **WAN de serviço** da bancada (caminho do modelo de dados), não a de gerência | responsável | pendente |
| 5 | Janela de baixa carga e quem acompanha | responsável | pendente |
| 6 | Edge **reimplantado antes da nuvem**, com a seção `speed` (ver `docs/addenda/v2.2-speed/EDGE_CONFIG.md`) | operação | pendente |
| 7 | Nuvem com as migrações 0034/0035 e a flag `speed_diagnostics` ligada só no provedor da bancada, junto de `bench_writes` | operação | pendente |

## 1. Planilha de homologação por modelo + firmware (preencher na execução real)

| Campo | Valor observado | Evidência (arquivo/ref.) | Verificado em |
|---|---|---|---|
| Fabricante / modelo / firmware | | | |
| Modelo de dados (Device:2 × IGD:1) e raiz usada | | | |
| `DownloadDiagnostics` presente e `DiagnosticsState` gravável (cache do ACS) | | | |
| `UploadDiagnostics` presente e `DiagnosticsState` gravável | | | |
| Folhas de resultado listadas (`BOMTime`, `EOMTime`, `TestBytesReceived`, `TotalBytesReceived`, `TotalBytesSent`, `TestBytesSent`?) | | | |
| Caminho da WAN de serviço (`speed_wan_interface`) e por que não é a de gerência | | | |
| Comportamento do aparelho diante de um **3xx** de um destino permitido (segue / não segue) | | | |
| Download: 3 repetições (Mbps, duração, confiabilidade) | | | |
| Upload: 3 repetições (Mbps, duração, confiabilidade) | | | |
| Comparação com medição **cabeada** de referência (mesmo nó, mesma janela) | | | |
| Concorrência: segundo pedido durante o teste foi recusado (`cpe_busy`)? | | | |
| Resultado após o teste: aparelho sem tarefa pendente no ACS, serviço do cliente de bancada intacto | | | |

## 2. Procedimento (cada passo registra quem, quando e o resultado)

1. **Preparar sem tráfego.** No servidor do Edge, escrever a seção `speed` e `speed_wan_interface` (modo 0600); a `allowlist` inclui cada `host:port` do nó. O Edge só sobe com a configuração válida. Implantar o **Edge primeiro**, depois a nuvem; conferir `go test` e `pytest` verdes no build implantado.
2. **Cadastrar o destino lógico** (sem endereço): `speed-endpoint-set <tenant> <id> <rótulo> CORE|INTERNET <região> on --edge <id-do-edge>`. O Edge informa a saúde em até 5 minutos; a tela só libera o teste com a palavra `ok` recente (30 min).
3. **Registrar o que o aparelho faz com 3xx.** Em um endpoint de laboratório que responde 3xx para um destino de captura sob controle do dono, registrar o comportamento observado e gravar a linha do registro: `capability-set <tenant> <fab> <modelo> <firmware> tr069 speed_test_redirect_probe supported|unsupported observed --evidence … --verified-at …` (`supported` = **não segue**). Alternativa: confirmar por escrito a ACL de saída e gravar `speed_test_egress_acl … supported observed` com a evidência. Sem uma das duas, o teste continua não elegível (`redirect_unverified`).
4. **Registrar a evidência da operação.** Para cada operação (`speed_test_download`, `speed_test_upload`): `capability-set … tr069 <operação> supported identified --evidence … --verified-at …` (condição da primeira execução), `bench-authorize … --first-run --speed-target <id> --speed-profile 10mb` pelo responsável (uso único, janela curta). A primeira execução gera o arquivo de evidência do ADR-0030 item 7 (hash da intenção, identidades, estado antes/depois, versões, aprovador, horário, aceite); só então a entrada `observed` pode ser gravada com `--evidence-file`.
5. **Executar, uma pessoa de cada vez:** quem pede (`diagnostics:speed_run`) ≠ quem aprova (`jobs:approve`) ≠ quem autorizou (`bench:authorize`). Pedir o download, aprovar, aguardar o resultado; depois o upload. Repetir 3 vezes cada (nova autorização de uso único por execução).
6. **Conferir cada resultado** contra a medição cabeada. Um resultado Parcial ou Inconclusivo **não** vira evidência de capacidade; repetir com tamanho maior ou investigar o motivo exibido.
7. **Fechar.** Aparelho sem tarefa pendente no ACS; Edge sem arquivo de restauração; alvo **destravado** apenas se o responsável reconciliar (`bench-unlock … --reason …`); planilha da seção 1 preenchida com referências, não com prints de dados de cliente.

## 3. Critérios de aceite do pacote (todos, com evidência real)

- Compatibilidade confirmada por modelo + firmware (planilha da seção 1 completa e referenciada no registro de capacidades).
- 3 repetições por sentido coerentes entre si e com a referência cabeada, dentro do que o responsável aceitar por escrito.
- Nenhum teste iniciou sem pedido, aprovação e autorização; segundo pedido simultâneo recusado.
- Nó de teste sem redirecionamento e com ACL/prova de egresso; nada de endereço na nuvem, na tela ou no repositório.
- RBAC, tenant e auditoria (`speed.requested`, `speed.blocked`, `job.*`) conferidos.
- Piloto com registros reais; fallback da UI e flag (desligar `speed_diagnostics` esconde a aba e as rotas respondem 403).
- Codex sem CRITICAL/HIGH sobre o que foi implantado; **aceite explícito do responsável** para ligar a flag além da bancada (isso exige ADR novo/emenda: este guia não abre a frota).

## 4. Voltar atrás

Desligar `speed_diagnostics` no provedor (a aba some e as rotas respondem 403); `bench_writes` desligado fecha qualquer escrita de bancada; revogar autorizações abertas (`DELETE /v1/bench/authorizations/{id}` ou CLI); desligar `speed.enabled` no Edge e reiniciá-lo. As tabelas aditivas podem ficar.

## 5. Não fazer

Usar ONT de cliente; apontar o nó para endereço que não seja do provedor; guardar URL/endereço do nó fora do servidor do Edge; repetir às cegas um teste `UNKNOWN`; ligar a flag em produção sem o aceite.
