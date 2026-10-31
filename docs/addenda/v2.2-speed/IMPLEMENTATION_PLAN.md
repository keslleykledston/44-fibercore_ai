# Speed Diagnostics (TR-143) — plano de implementação incremental

Regra: nada de teste real em ONT, nada de nó de teste exposto, nada de tráfego sem autorização do responsável. Flag `speed_diagnostics` **desligada** até aceite. Cada PR: Codex adversarial até "approve", `secrets-scan.sh`, testes, ADR/CHANGELOG/TEST_EVIDENCE.

## PR 0 — Descoberta (este)
Docs: `CURRENT_STATE.md`, `GAP_MAP.md`, este plano, cópia de referência do pacote. Sem código. Entra o ADR-0038 (decisão do terceiro gate) junto do PR 1.

## Decisões de desenho (propostas; peço objeção antes do PR 1 só se discordar)
1. **Nome e flag:** `speed_diagnostics` (não "SD-001", que já é o pack de Smart Diagnostics). Permissão `diagnostics:speed_run` (R2, escopável; MFA recente conforme a política única da plataforma).
2. **Operações de job:** `speed_test_download` e `speed_test_upload` (R1, 0 aprovações, alvo `cpe`): o operador que inicia é autorizado pela permissão + confirmação do aviso de consumo; a segurança vem do gate (item 3), não de uma aprovação por teste. Escrita bloqueada (`operation_not_homologated`) até o gate abrir.
3. **Gate `speed` (terceiro caminho, default fechado)** — abre só se TODOS: flag do provedor; registro de capacidades `supported` + `observed|certified` com evidência para o `(vendor, model, firmware, tr069, operação)` exato; interface WAN de serviço verificada (referência de homologação ↔ `cpe_config_fields`); destino lógico habilitado e saudável; vínculo ONU↔CPE confirmado com PON conhecida; slots livres (ONT, PON, tenant); Edge do alvo é o do job e declara o suporte (`SPEED_EDGE_SUPPORT`). Qualquer fonte ausente/ilegível recusa.
4. **Destinos:** a nuvem só conhece o **id lógico** (`speed_endpoints`: nome, alvo CORE|INTERNET, região, habilitado, saúde); o Edge mapeia id → URL na própria config (lista fechada, tamanho de arquivo por perfil, sem redirecionamento, só HTTP GET/PUT). O envelope assinado nunca leva URL.
5. **Resultado:** o Edge reporta contadores brutos (estado, BOM/EOM, bytes, HTTP da tarefa, tempo de polling); a **nuvem calcula** Mbps e qualidade com função pura testável. Sem dado confiável = `—`/inconclusivo, nunca 0.
6. **Conclusão:** polling controlado (sem Inform nativo no NBI); nenhum reenvio de `Requested`; timeout 120 s por direção (teto configurável).

## PR 1 — Nuvem (API + banco + gate), com Edge falso
- Migração aditiva **0034**: `speed_endpoints`, `speed_test_runs` (RLS forçada; grants mínimos; CHECK de estados/qualidade/alvo; sem colunas de URL, token ou payload).
- `app/core/speed.py`: catálogo de erros/blockers estáveis, classificação de capacidade, `compute()`, regras de qualidade, reserva de slots (advisory lock) — funções puras + testes T09–T11, T19.
- `app/api/speed.py` (router novo; nada alterado nos existentes): `GET /v1/cpes/{id}/speed/capabilities`, `POST /v1/cpes/{id}/speed/runs` (`{target, key}`; sem URL), `GET …/runs`, `GET …/runs/{runId}`, `GET /v1/speed/health`; BFF espelha. `jobs.py`: duas entradas em `OPERATIONS` e o gate `speed` em `_blocked_reason`/dispatch (aditivo, `HOMOLOGATED_WRITES` intacto); extensão do recebimento de resultado para validar o formato fechado dos contadores.
- Permissão `diagnostics:speed_run`, flag `speed_diagnostics`, `team_info`, matriz RBAC, auditoria.
- CLI do dono: `speed-endpoint-set` (id lógico, alvo, região, habilitado) — sem URL; `capability-set` já existe para a evidência.
- Testes: T01–T05, T07–T09, T12–T15, T20 com Edge falso (jobs/resultado simulados), RLS/tenant, SSRF por construção (não há campo de URL), concorrência (2 requisições simultâneas → 1×409), flag OFF sem escrita, regressão da suíte completa.
- ADR-0038 (gate, destinos, conclusão por polling, limites).

## PR 2 — Edge (Go) com NBI falso
- `internal/speed` + cliente NBI de escrita próprio e fechado (`setParameterValues` só com os 3–4 nomes TR-143 do root detectado; verificação de fonte ampliada para permitir exatamente isso e nada mais).
- Descoberta: presença de `DownloadDiagnostics`/`UploadDiagnostics`, `_writable`, root único (Device:2 ou IGD:1, nunca misturados), `DownloadTransports` quando existir; relatório de observações (`speed-capability`) tipado ao cloud.
- Execução: claim durável + lease + ritmo persistido (reuso do que o bench já tem), 200/202, polling 3–5 s, frescor (`BOMTime` dentro da janela do pedido, `_timestamp`), `Error_*`, timeout, limpeza de tarefa, sem reenvio; URL só da config local; tamanho por perfil.
- Testes com NBI falso: T01–T03, T05–T09, T16–T19 (Device:2, IGD:1, bridge, só download, 202, stale, erro, timeout, nó sem PUT).
- Deploy: **Edge primeiro**, depois nuvem (mesma ordem já usada); sem config `speed` o Edge recusa o job.

## PR 3 — UX, ajuda e guia de homologação
- `SpeedTestSection` no painel da ONU (aba "Teste de banda") e bloco na ONU 360°: estado de compatibilidade, segmented Core/Internet (desabilitado sem destino pronto), Iniciar com aviso de consumo, acompanhamento por direção, KPIs DL/UL (máx. 2), confiabilidade, detalhes sob demanda, histórico (5), microcopy do pacote; Esc/teclado/foco como o resto do painel.
- Ajuda: `rede/testar-banda` + manifesto; capturas **reais** do LAB (flag ligada só no LAB para a captura, estado bloqueado/indisponível real) e capturas de cenário E2E **rotuladas** para em teste/resultado/parcial/timeout; `validate_help.py` PASS.
- Guia de homologação (`docs/operations/SPEED_HOMOLOGACAO.md`): planilha por `vendor/model/firmware/root/método/WAN`, procedimento do piloto (3 repetições, comparação cabeada), critérios de aceite do pacote. **Sem evidência simulada.**
- Lovable: só se houver divergência visual a decidir; a UI nasce dos componentes locais (como nos PRs 100/101/103).

## Fora de qualquer PR deste ciclo
Nó de teste (implantação/exposição), execução em ONT real, ligar a flag em produção, USP, copiloto, ERP, agendamento, jitter/perda.

## Dependências que só o responsável resolve
1. Autorizar (ou não) a homologação na ONT de bancada Huawei EG8145V5 (nova manobra; escopo "teste de banda" via TR-143).
2. Informar/aprovar um nó de teste já controlado pelo provedor (Core e, se houver, Internet) e quem libera ACL/firewall; sem isso o catálogo fica vazio e o estado é `NO_TARGET`.
3. Dizer qual é a WAN de serviço da bancada (VLAN/instância), ou autorizar a leitura que a identifique.
4. Janela de baixa carga para o piloto.

## Pronto para ativar quando (do pacote, mantido)
Capacidade do nó validada; ACL/firewall; RBAC/tenant testados; piloto com registros reais; fallback da UI e flag funcionais; Codex aprovou; responsável autorizou a ativação.
