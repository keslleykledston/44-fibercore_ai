# Speed — 1ª tentativa real de download na ONT de bancada — 2026-10-31 — NÃO INICIOU (falha antes de qualquer escrita)

Escopo: SOMENTE a ONT de bancada (Huawei EG8145V5 `V5R019C10S350`, serial de bancada `…7AA5`). Sem endereço, credencial ou dado de cliente. **Não é evidência de capacidade**: nenhuma medição foi feita.

## O que foi feito
- Registro `speed_test_download` = `supported`/`identified` (evidência: `H-speed-sonda-3xx-eg8145v5-2026-10-31.md`); aceite do risco de 3xx vigente (`ACEITE-risco-3xx-eg8145v5-2026-10-31.md`); autorização de uso único do dono com `--first-run` (par exato `core-lab` + `10mb`); flag `speed_diagnostics` ligada só na janela e desligada ao fim; pedido (conta de serviço A), aprovação (conta de serviço B), pré-checagem do ACS (Inform recente, 0 tarefas pendentes).
- **Achado 1 (corrigido, PR `fix/speed-first-run-request`):** o endpoint de pedido exigia entrada `observed` e barrou o caminho de primeira execução que o gate já aceitava. Corrigido, com Codex em 2 rodadas.
- **Achado 2 (aberto):** o job foi aprovado e despachado; o Edge o aceitou e terminou em 0,2 s como `FAILED` / `speed_not_started`, porque a leitura prévia do objeto de diagnóstico exige uma tarefa `getParameterValues` com Connection Request e o ACS respondeu **HTTP 202 (tarefa enfileirada: o Connection Request não completou)**; o motivo não foi provado. O Edge removeu a própria tarefa e não escreveu nada.

## Diagnóstico do Achado 2 (leituras e uma tarefa de leitura inofensiva; nada foi escrito na ONT)
- Duas tarefas diretas `getParameterValues` de `DeviceInfo.UpTime` com Connection Request: **202 em 0,04 s** nas duas; as duas removidas; 0 tarefas pendentes e 0 falhas depois.
- A porta de Connection Request da ONT **abre** por TCP a partir do host do ACS, e a ONT informa normalmente (Inform a cada ~5 min; `PeriodicInformInterval` = 300). Ou seja: alcançável, mas o ACS devolve 202 na hora, sem completar o Connection Request — **hipótese não confirmada**: divergência de credencial/URL de Connection Request (os logs de depuração do GenieACS exigem root).
- Contraste: o H2 (reboot, 2026-10-30 03:31) e as leituras ativas de 2026-10-29 funcionaram com Connection Request nesta mesma ONT; a ONT reiniciou depois (2026-10-30 06:34).
- Tarefas enfileiradas **sem** Connection Request são executadas no Inform seguinte (~60 s na sonda de 3xx).

## Estado depois
Nenhuma tarefa pendente; `DiagnosticsState` inalterado; bancada travada pelo `FAILED` e **destravada** com `bench-unlock` e este motivo (job falhou antes da escrita: certo, não ambíguo); flag `speed_diagnostics` desligada; autorização de uso único consumida.

## Próximo (decisão do responsável)
(a) Investigar e corrigir o Connection Request no ACS (hipótese: credencial/URL da ONT de bancada; liga-se à pendência de credenciais CWMP). (b) Ou aprovar uma emenda para o Edge executar o teste em "modo fila" (sem Connection Request: espera o Inform, com prazo e limpeza da própria tarefa), mudança que relaxa o desenho atual de resultado certo e precisa de ADR.
