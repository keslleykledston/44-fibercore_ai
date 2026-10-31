# Speed Diagnostics (TR-143) — plano de implementação incremental

Regra: nada de teste real em ONT, nada de nó de teste exposto, nada de tráfego sem autorização do responsável. Flag `speed_diagnostics` **desligada** até aceite. Cada PR: Codex adversarial até "approve", `secrets-scan.sh`, testes, ADR/CHANGELOG/TEST_EVIDENCE.

## PR 0 — Descoberta (este)
Docs: `CURRENT_STATE.md`, `GAP_MAP.md`, este plano, cópia de referência do pacote. Sem código. Entra o ADR-0038 (decisão do terceiro gate) junto do PR 1.

## Decisões de desenho (revisadas após o Codex r1 do PR 0)
1. **Nome e flag:** `speed_diagnostics` (não "SD-001", que já é o pack de Smart Diagnostics). Permissão `diagnostics:speed_run` (R2, escopável; MFA recente conforme a política única da plataforma).
2. **Nenhum caminho de escrita novo e mais amplo.** O teste de banda escreve no CPE (`DiagnosticsState=Requested` gera tráfego), então fica sob **ADR-0010 (escrita bloqueada até homologação por firmware), ADR-0025 (testes ativos só depois do ADR-SD-003) e ADR-0030 (exceção de bancada)**. Nesta entrega:
   - as operações `speed_test_download` / `speed_test_upload` entram como **linhas novas do catálogo de bancada** (`BENCH_OPS`, emenda ao ADR-0030): só o CPE de bancada, parâmetros fechados (`target` = id lógico do destino, `profile` = tamanho de arquivo de uma lista), flag `bench_writes`, registro de capacidades com evidência por `(vendor, model, firmware, tr069, operação)`, **autorização prévia de uso único do dono**, separação de atores (quem autoriza ≠ quem pede ≠ quem aprova), `claim` durável, `lease`, confirmação do dispositivo no ACS e resultado incerto = `UNKNOWN` com trava (nunca repetido às cegas);
   - para qualquer outro CPE a operação é recusada com `operation_not_homologated` (o bloqueio global `HOMOLOGATED_WRITES` vazio **não muda**);
   - abrir o teste para a frota depois do piloto é uma **decisão separada**: exige ADR novo/emenda (cumprindo o papel do ADR-SD-003 para esta fatia) e aprovação explícita do responsável. O ADR-0038 descreve os critérios, mas **não abre** nada.
   - a flag `speed_diagnostics` esconde/mostra a seção e as rotas; ela **não** substitui o gate de escrita.
3. **Três camadas separadas (não confundir):** (a) **observação** pelo Edge (presença do objeto, `_writable`, root): informa a UI, nunca autoriza; (b) **homologação** (evidência no registro de capacidades + referência da WAN de serviço escrita pelo dono): é o que torna a operação elegível; (c) **autorização operacional** (uso único, janela, ator): é o que abre UMA execução. `cpe_config_fields` (`wan.type`, VLAN) é só sinal auxiliar: se a referência homologada da WAN de serviço não casar com o que o CPE reporta, a execução é recusada (`WAN_UNVERIFIED`).
4. **Destinos:** a nuvem só conhece o **id lógico** (`speed_endpoints`: nome, alvo CORE|INTERNET, região, habilitado, saúde); o Edge mapeia id → URL na própria config local. **Controles verificáveis no Edge (critério de aceite do PR 2):** esquema e porta fixos por endpoint (HTTP; sem URL com credencial/token/query); host preferencialmente IP literal, ou nome resolvido **uma vez no carregamento da config e fixado** (o CPE recebe o IP, não o nome: sem DNS rebinding); recusa de loopback, link-local (inclui 169.254.0.0/16), multicast, não especificado e faixas de metadados; `INTERNET` recusa destino privado/CGNAT/ULA; `CORE` só aceita destino dentro de `core_cidrs` declarados na config; sondagem de saúde feita pelo Edge (GET pequeno, sem redirecionamento, comprimento esperado) antes de cada execução; tamanho de arquivo só de lista fechada; config inválida = o Edge não sobe o módulo. **Redirecionamento é requisito de homologação por firmware, não só da sondagem do Edge:** quem faz o GET/PUT é o CPE, e a sondagem do Edge não prova o que o cliente TR-143 do aparelho faz diante de um 3xx. Por isso: (i) o nó de teste **não pode redirecionar** (item de aceite do nó, verificado na sondagem); (ii) na homologação de cada modelo+firmware o dono registra no registro de capacidades, como evidência, o comportamento observado do CPE diante de um 3xx de um destino permitido (segue ou não segue; teste contra um endpoint de laboratório que responde 3xx para um destino de captura sob controle do dono); (iii) **sem essa evidência, ou se o CPE seguir o redirecionamento, a operação continua não elegível** a menos que o controle de rede (ACL/firewall de saída da WAN de serviço, restringindo o destino do tráfego gerado pelo CPE aos nós de teste) esteja confirmado pelo operador como item do checklist de ativação. O controle de rede é responsabilidade do operador e fica no checklist, não é presumido.
5. **Resultado:** o Edge reporta contadores brutos (estado, BOM/EOM, bytes, HTTP da tarefa, tempo de polling); a **nuvem calcula** Mbps e qualidade com função pura testável. Sem dado confiável = `—`/inconclusivo, nunca 0.
6. **Conclusão:** polling controlado (sem Inform nativo no NBI); nenhum reenvio de `Requested`; timeout 120 s por direção (teto configurável).

## PR 1 — Nuvem (API + banco + gate), com Edge falso
- Migração aditiva **0034**: `speed_endpoints`, `speed_test_runs` (RLS forçada; grants mínimos; CHECK de estados/qualidade/alvo; sem colunas de URL, token ou payload).
- `app/core/speed.py`: catálogo de erros/blockers estáveis, classificação de capacidade, `compute()`, regras de qualidade, reserva de slots (advisory lock) — funções puras + testes T09–T11, T19.
- `app/api/speed.py` (router novo; nada alterado nos existentes): `GET /v1/cpes/{id}/speed/capabilities`, `POST /v1/cpes/{id}/speed/runs` (`{target, key}`; sem URL), `GET …/runs`, `GET …/runs/{runId}`, `GET /v1/speed/health`; BFF espelha. `jobs.py`: duas entradas em `OPERATIONS` e em `BENCH_OPS` (`app/core/bench.py`), com a validação dos parâmetros fechados; **nenhum gate novo** (`HOMOLOGATED_WRITES` e o gate de bancada intactos); extensão do recebimento de resultado para validar o formato fechado dos contadores; a autorização de bancada é a que já existe (`bench-authorize`, uso único), com a operação nova.
- Permissão `diagnostics:speed_run`, flag `speed_diagnostics`, `team_info`, matriz RBAC, auditoria.
- CLI do dono: `speed-endpoint-set` (id lógico, alvo, região, habilitado) — sem URL; `capability-set` já existe para a evidência.
- Testes: T01–T05, T07–T09, T12–T15, T20 com Edge falso (jobs/resultado simulados), RLS/tenant, SSRF por construção (não há campo de URL), concorrência (2 requisições simultâneas → 1×409), flag OFF sem escrita, regressão da suíte completa.
- ADR-0038 + emenda ao ADR-0030 (operações de teste de banda no catálogo de bancada; critérios — sem abrir a frota — para uma decisão futura; destinos; conclusão por polling; limites).

## PR 2 — Edge (Go) com NBI falso
- `internal/speed` + cliente NBI de escrita próprio e fechado (`setParameterValues` só com os 3–4 nomes TR-143 do root detectado; verificação de fonte ampliada para permitir exatamente isso e nada mais).
- Descoberta: presença de `DownloadDiagnostics`/`UploadDiagnostics`, `_writable`, root único (Device:2 ou IGD:1, nunca misturados), `DownloadTransports` quando existir; relatório de observações (`speed-capability`) tipado ao cloud.
- Execução: claim durável + lease + ritmo persistido (reuso do que o bench já tem), 200/202, polling 3–5 s, frescor (`BOMTime` dentro da janela do pedido, `_timestamp`), `Error_*`, timeout, limpeza de tarefa, sem reenvio; URL só da config local; tamanho por perfil.
- Testes com NBI falso: T01–T03, T05–T09, T16–T19 (Device:2, IGD:1, bridge, só download, 202, stale, erro, timeout, nó sem PUT).
- Deploy: **Edge primeiro**, depois nuvem (mesma ordem já usada); sem config `speed` o Edge recusa o job.

## PR 3 — UX, ajuda e guia de homologação
- `SpeedTestSection` no painel da ONU (aba "Teste de banda") e bloco na ONU 360°: estado de compatibilidade, segmented Core/Internet (desabilitado sem destino pronto), Iniciar com aviso de consumo, acompanhamento por direção, KPIs DL/UL (máx. 2), confiabilidade, detalhes sob demanda, histórico (5), microcopy do pacote; Esc/teclado/foco como o resto do painel.
- Ajuda: `rede/testar-banda` + manifesto; capturas **reais** do LAB (flag ligada só no LAB para a captura, estado bloqueado/indisponível real) e capturas de cenário E2E **rotuladas** para em teste/resultado/parcial/timeout; `validate_help.py` PASS.
- Guia de homologação (`docs/operations/SPEED_HOMOLOGACAO.md`): planilha por `vendor/model/firmware/root/método/WAN/comportamento diante de 3xx`, procedimento do piloto (3 repetições, comparação cabeada), critérios de aceite do pacote. **Sem evidência simulada.**
- Lovable: só se houver divergência visual a decidir; a UI nasce dos componentes locais (como nos PRs 100/101/103).

## Fora de qualquer PR deste ciclo
Nó de teste (implantação/exposição), execução em ONT real, ligar a flag em produção, USP, copiloto, ERP, agendamento, jitter/perda.

## Dependências que só o responsável resolve
1. Autorizar (ou não) a homologação na ONT de bancada Huawei EG8145V5 (nova manobra por `bench-authorize`, uso único; escopo "teste de banda" via TR-143) e aprovar a emenda ao ADR-0030.
2. Informar/aprovar um nó de teste já controlado pelo provedor (Core e, se houver, Internet) e quem libera ACL/firewall; sem isso o catálogo fica vazio e o estado é `NO_TARGET`.
3. Dizer qual é a WAN de serviço da bancada (VLAN/instância), ou autorizar a leitura que a identifique.
4. Janela de baixa carga para o piloto.

## Pronto para ativar quando (do pacote, mantido)
Capacidade do nó validada; ACL/firewall; RBAC/tenant testados; piloto com registros reais; fallback da UI e flag funcionais; Codex aprovou; responsável autorizou a ativação.
