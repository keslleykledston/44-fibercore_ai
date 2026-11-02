# Reautorização de ONU (`onu_reauthorize`, H5) — ONU de bancada Huawei na MA5608T — 2026-11-02

Evidência de manobra de bancada (ADR-0030, item 7 e emenda H5). Autorização do responsável: mensagem do chat de 2026-11-02 ("Autorizado executar o adr-0030 completo … mas efetue testes apenas nas onu de bancada"). Escopo: UMA ONU (a de bancada declarada) e UMA service-port. Nenhuma ONU de cliente foi tocada.

- **Hash da intenção:** `e6ce40e4c90cdaed96cd20eed1eb4b73488cb645d559ed0b1fb5abdc6d5428d3` (job `97046bd6-5881-4061-a7ba-7a63362b9ecd`, operação `onu_reauthorize`, alvo CPE de bancada Huawei).
- **Identidades observadas:** ONU de bancada pelo serial GPON de 16 hexadecimais (confere com o da configuração local do Edge e com o do CPE de bancada no ACS), posição `0/0/14`, ONT-ID `10`; antes e depois: ativa, online, `normal`, `match`. Vínculo OLT↔ACS: o CPE de bancada é o mesmo equipamento (serial do ACS = serial da OLT), conferido antes da tarefa pelo Edge.
- **Estado antes (baseline, só leitura, relido pelo Edge antes de enviar qualquer comando):** perfil de linha 179, perfil de serviço 179, descrição `5`, UMA service-port (índice 1708, VLAN 1400, gpon 0/0/14 ONT 10, GEM 1, fluxo `vlan` 1400, `translate`, sem tabelas de tráfego, `up`). Os identificadores acima estão na configuração local do Edge (`bench.olt.reauthorize`), nunca na nuvem.
- **Estado depois:** o pós-check do próprio Edge (`postcheck_ok: true`): lista e detalhe da service-port e os perfis/descrição da ONU **iguais ao baseline**, ONU online com os mesmos perfis. Leitura independente feita à parte, depois do intervalo de 15 min da OLT: ver "Verificação independente" abaixo.
- **Resultado da restauração:** o ciclo terminou em `Done` pelo caminho principal; o caminho de restauração não foi necessário nesta execução. Nas duas execuções anteriores a restauração foi acionada e terminou incompleta por causa dos defeitos descritos em "Histórico das tentativas" (a ONU foi reposta à mão e conferida por leitura).
- **Versões:** Edge `0.1.0-lab-9b67bb5`; OLT Huawei MA5608T, firmware `MA5600V800R015C00`; API na `main` com migração 0044; firmware do CPE de bancada: o registrado no ACS (sem mudança).
- **Aprovador:** job pedido e aprovado por conta de serviço descartável `isp_admin` (criada pelo owner CLI e desativada ao fim); autorização prévia de uso único `63852351-2dee-47a2-85f8-875b6c4801c6` (`--first-run`, janela 19:54–20:40 UTC), dada pelo dono pelo owner CLI com base na ordem do responsável no chat de 2026-11-02.
- **Horário:** despacho 19:55:44 UTC, concluído 19:56:44 UTC (job criado 19:55:29, finalizado 19:56:44).
- **Aceite do responsável:** **PENDENTE.** A capacidade `huawei/MA5608T/MA5600V800R015C00/olt/onu_reauthorize` continua `supported` / **`identified`** até o aceite registrado (`capability-set … observed --evidence-file` com este arquivo).

## O que a manobra fez (sequência fechada)
`undo service-port 1708` → `ont delete 14 10` → o serial apareceu em `display ont autofind all` (consultado em polling) → `ont add 14 10 sn-auth <serial> omci ont-lineprofile-id 179 ont-srvprofile-id 179 desc 5` → espera da ONU online com o baseline → `service-port 1708 vlan 1400 gpon 0/0/14 ont 10 gemport 1 multi-service user-vlan 1400 tag-transform translate` → comparação final. Nada fora da lista fechada de comandos do ADR-0030 foi enviado (além dela, só `enable`, `config`, `interface gpon 0/0`, `quit` e leituras `display`).

## Histórico das tentativas (três execuções reais; só a terceira passou)
1. **Job `ca96ac06…` (17:37 UTC): falha segura, NADA enviado.** A leitura de baseline falhou antes do primeiro comando que altera: os campos de `display service-port <índice>` vêm recuados na OLT real e o parser esperava coluna 0. Corrigido (fixtures no layout real; Codex r11 approve).
2. **Job `6126ffdb…` (18:03 UTC): FALHOU, deixou a ONU de bancada autorizada e SEM service-port.** O autofind era lido uma única vez, logo depois do `ont delete`, e a ONU ainda não tinha sido redescoberta; o restauro rodou o `ont add`, mas o comando estourou `command timeout` (a mesma causa da tentativa seguinte; nesta o erro ainda não informava o fim da tela, então a causa foi inferida e depois confirmada na tentativa 3). A ONU ficou online com os perfis do baseline e sem a service-port; foi reposta à mão com um único comando do baseline (o mesmo `service-port …` da lista) e conferida por leitura (`up`, VLAN 1400, GEM 1). Correção: autofind em polling limitado pela espera da manobra (Codex r1 approve).
3. **Job `3898104a…` (19:16 UTC): FALHOU de novo, mesma consequência.** O `ont add` (já executado) estourou `command timeout` com a tela no prompt: a OLT **quebra em 80 colunas o eco de comando longo** (`␠ESC[1D` + próximo caractere) e o Edge exigia o eco idêntico ao comando para considerar a saída completa. A ONU foi reposta à mão do mesmo jeito e conferida. Correção: `joinWrappedEcho` junta o eco só na primeira linha e só em coluna de quebra real; teste de ponta a ponta com dispositivo falso que ecoa como a OLT real e FALHA sem a correção (Codex r2 approve, após um achado high que restringiu a regra).
4. **Job `97046bd6…` (19:55 UTC): SUCCEEDED**, com o Edge `0.1.0-lab-9b67bb5`.

Lições: (a) uma falha parcial na bancada é real e o desenho de restauração por leitura + só adicionar funcionou como previsto; (b) o `command timeout` agora informa o fim da tela (hex longos ocultos), o que tornou a segunda causa visível; (c) cada trava de escrita foi destravada só depois de reconciliação por leitura registrada (`bench-unlock` com motivo).

## Confirmações observadas na OLT
O `undo service-port` e o `ont delete` concluíram. O `ont delete` está configurado para aceitar apenas a pergunta `Are you sure to delete the ONT(s)? (y/n)[n]:`; o Edge não registra se a pergunta foi feita, então **não foi observado** se a OLT pergunta. `undo service-port` não tem padrão: qualquer pergunta falharia fechado, e não falhou (logo, não perguntou ou a pergunta estava fora do que o Edge reconhece como pergunta). O texto exato continua a registrar por emenda quando for visto.

## Autofind real
O texto de uma entrada real de `display ont autofind all` foi capturado (no host do Edge, 0600) e destruído (`shred`) depois de escrever o parser: `olt.autofind` passou a ter parser tipado e fixture sintético no layout real (lista vazia e UMA entrada). `Password`, `Loid` e `Checkcode` da ONT nunca são lidos nem enviados. O layout com várias entradas não foi observado.

## Verificação independente
(a preencher com a leitura de 20:12 UTC)
