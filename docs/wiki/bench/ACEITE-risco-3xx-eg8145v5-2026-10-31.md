# Aceite do risco de redirecionamento 3xx — Huawei EG8145V5 — 2026-10-31

Instrumento da emenda aprovada do ADR-0038 (opção C). A decisão que o gate lê é a linha `speed_risk_acceptances` do banco; este arquivo é a cópia legível, identificada pelo hash gravado na linha.

Fabricante: Huawei Technologies Co., Ltd
Modelo: EG8145V5
Firmware: V5R019C10S350
Destinos aceitos (ids lógicos, tipo CORE): core-lab
Data: 2026-10-31
Validade: até 2026-11-30 (30 dias; o limite do ADR é 90)

Escopo: SOMENTE a ONT de bancada deste modelo e firmware, SOMENTE para o nó de teste `core-lab` (o `tools/speed-node` do provedor), com autorização de uso único em cada execução e a flag `speed_diagnostics` ligada só para o provedor da bancada. Não vale para ONT de cliente, para outro firmware nem para destino INTERNET.

Base factual: a sonda real (`docs/wiki/bench/H-speed-sonda-3xx-eg8145v5-2026-10-31.md`) mostrou que esta ONT SEGUE redirecionamento 3xx.

Risco residual: se o nó de teste fosse comprometido ou mal configurado e passasse a responder 3xx, a ONT de bancada seguiria para o destino indicado e geraria tráfego até lá. Mitigações: nó sob controle do provedor que nunca emite 3xx (testado), lista de origens explícita, janela e uso único por execução, envelope de vida curta, validade desta aceitação e firmware exato. Reversão: `speed-acceptance-revoke` (efeito imediato para todo job ainda não despachado) ou `speed.enabled=false` no Edge.

Aprovado por: Responsável do projeto (aprovação registrada no chat da sessão, emenda do ADR-0038 de 2026-10-31)
