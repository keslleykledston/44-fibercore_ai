# Aceite do risco de redirecionamento 3xx — ZTE F670L — 2026-11-01

Instrumento da emenda aprovada do ADR-0038 (opção C). A decisão que o gate lê é a linha `speed_risk_acceptances` do banco; este arquivo é a cópia legível, identificada pelo hash gravado na linha.

Fabricante: ZTE
Modelo: F670L
Firmware: V9.0.11P1N10B
Destinos aceitos (ids lógicos, tipo CORE): core-lab
Data: 2026-11-01
Validade: até 2026-11-30 (29 dias; o limite do ADR é 90)

Escopo: SOMENTE a ONT de bancada deste modelo e firmware, SOMENTE para o nó de teste `core-lab` (o `tools/speed-node` do provedor), com autorização de uso único em cada execução e a flag `speed_diagnostics` ligada só para o provedor da bancada. Não vale para ONT de cliente, para outro firmware nem para destino INTERNET.

Base factual: a sonda real (`docs/wiki/bench/H-speed-sonda-3xx-zte-f670l-2026-11-01.md`) mostrou que esta ONT SEGUE redirecionamento 3xx.

Risco residual: se o nó de teste fosse comprometido ou mal configurado e passasse a responder 3xx, a ONT de bancada seguiria para o destino indicado e geraria tráfego até lá. Mitigações: nó sob controle do provedor que nunca emite 3xx (testado), lista de origens explícita, janela e uso único por execução, flag ligada só nas janelas autorizadas. A origem pública da ZTE (vista pelo host do nó na sonda) NÃO teve a natureza confirmada: não se sabe se é um endereço de NAT compartilhado nem quem mais o usa. Se for compartilhado, incluí-lo na lista do nó permite que outros equipamentos por trás do mesmo endereço peçam bytes aleatórios ao nó de forma repetida, em sequência e sem limite de volume acumulado: o limite de transferências simultâneas do nó restringe só pedidos ativos ao mesmo tempo, e o nó não tem controle de taxa ou de volume total. O consumo de banda e de recursos do nó por origens desconhecidas fica, portanto, sem teto efetivo e não é mitigado por este aceite. O responsável autorizou a inclusão ciente dessa incerteza ("4. prossiga", chat de 2026-11-01); a incerteza permanece registrada aqui e não é tratada como resolvida.

Aprovado por: Responsável do projeto (aprovação registrada no chat da sessão em 2026-11-01: "3. autorizo")
