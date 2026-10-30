# Evidência de manobra de bancada (ADR-0030, item 7) — MODELO

Copie para `docs/wiki/bench/<fase>-<operação>-<data>.md` e preencha. Cada campo é checado pelo owner CLI (`capability-set --evidence-file`) antes de a capacidade `observed` ser registrada. Sem credencial, endereço IP, nome de cliente nem saída crua de equipamento.

- **Hash da intenção:** (sha256 da intenção executada, do job)
- **Identidades observadas:** (antes: OUI, classe e serial do CPE no ACS; serial e posição da ONU na OLT; o vínculo observado)
- **Estado antes:** (o estado de partida capturado)
- **Estado depois:** (o estado observado depois da manobra)
- **Resultado da restauração:** (como o retorno ao estado seguro foi OBSERVADO)
- **Versões:** (Edge, firmware do CPE, firmware da OLT)
- **Aprovador:** (quem aprovou o job; quem autorizou, e o id da autorização)
- **Horário:** (início e fim, com fuso)
- **Aceite do responsável:** (registro do aceite para avançar de fase)
