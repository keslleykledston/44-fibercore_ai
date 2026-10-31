# H1 — evidência de vínculo ONU↔CPE — ZTE F670L — 2026-10-31 (SOMENTE LEITURA)

Escopo: **leitura**. Nenhuma escrita em equipamento, nenhum registro de alvo de bancada, nenhuma manobra. Complementa `H1-identificacao-zte-f670l-2026-10-31.md`, que deixou o vínculo **não confirmado**. Sem credencial, endereço, descrição de ONT ou dado de cliente: a saída crua da OLT não foi impressa nem versionada, e só os campos listados abaixo foram extraídos.

## Autorização
O responsável, no chat da sessão em 2026-10-31: "a ONT zte é de bancada tbm" e, antes, "acesse a OLT e colete estes dados". Escopo: UMA ONT (ONT-ID 11 da PON 0/0/14), duas consultas de leitura, uma execução. Isto **não** é a autorização para cadastrar a ZTE como alvo de bancada (ver "Pendente").

## Como foi coletado
- Edge `0.1.0-lab-9ec5221` com a nova lista `bench.read_only_onus` (ONUs de bancada adicionais, **só para captura de leitura**; escopo de ONU com posição exata; nunca PON; não participa de manobra). Código revisado pelo Codex (3 rodadas, approve; `raw/314` a `raw/316`).
- Captura supervisionada (ADR-0032) de `onu.info` e `onu.register`, ONT-ID 11 da PON 0/0/14, na sessão de coleta de 2026-10-31 23:20 UTC, dentro do guarda de sessão única (intervalo de 15 min). Saída crua: arquivo 0600 no host do Edge (apaga sozinho em 24 h); a cópia local foi apagada com `shred` logo após a extração.

## Observado na OLT (campos extraídos)
| Campo | Valor |
|---|---|
| Posição | PON `0/0/14`, ONT-ID `11` |
| Serial GPON | termina em `…D1EDA1A3` (igual ao serial no cache da coleta rotineira e ao trecho presente no SSID da ZTE lido no ACS) |
| **Tipo de equipamento registrado pela OLT** | **`F670LV9.0`** (o dispositivo no ACS é ZTE F670L) |
| Autenticação / estado | por SN; online; configuração normal; `match`; controle ativo |
| Distância | 160 m |
| Última queda | **2026-10-31 16:04:40 (−04:00) = 20:04:40 UTC**, causa **LOSi/LOBi** |
| Última subida | 2026-10-31 16:05:47 (−04:00) = 20:05:47 UTC (queda de ~67 s) |
| Tempo online na captura | 3 h 8 min |
| Histórico de registro da OLT (`register-info`) | 2 entradas, ambas por SN e tipo `F670LV9.0`: subida em 2026-10-30 22:08:15 (−04:00) e a de 2026-10-31 16:05:46 (−04:00) |
| TR-069 da OLT | desabilitado (a ZTE fala com o ACS pela própria WAN) |
| Descrição da ONT | existe (**não impressa**) |

## Leitura da evidência
- **Identidade (forte):** a OLT registra, na posição 0/0/14 ID 11, uma ONT de tipo `F670LV9.0` cujo serial GPON termina em `…D1EDA1A3`; o ACS tem exatamente um dispositivo ZTE F670L e o SSID dele contém esse mesmo trecho. Modelo e trecho do serial coincidem em três fontes independentes (OLT, cache de ONUs e ACS).
- **Linha do tempo (compatível, não exata):** a OLT viu a ONT cair às 20:04:40 UTC por LOSi/LOBi e voltar às 20:05:47; no ACS, o último Inform da ZTE foi às 20:08:31 UTC e ela só voltou às 22:22 UTC, quando entregou um evento `1 BOOT` atrasado. O uptime lido no ACS às 22:33 UTC (8.542 s) aponta boot por volta de 20:11 UTC, não 22:22: o reinício das 22:22 NÃO aparece como queda na OLT e não deve ser tomado como o reboot observado. A diferença de ~6 min entre a subida na OLT e o boot inferido pelo uptime não foi explicada.
- **Causa da queda de 20:04 UTC: não verificada.** LOSi/LOBi é perda de sinal óptico; pode ser fibra, conector ou o próprio equipamento.

## Conclusão
O vínculo está **bem sustentado por três evidências coincidentes (modelo registrado pela OLT, trecho do serial GPON, SSID)**, mas continua **sem a prova direta** de igualdade completa de serial entre a OLT e o próprio CPE (o ACS não expõe o GPON SN) e sem um reinício observado offline→online na OLT. Sugestão ao responsável: aceitar como suficiente ou pedir um reinício acompanhado com a ONT 11 observada na OLT. **Não registrei nenhum vínculo no FiberCore.**

## Pendente antes de qualquer alvo de bancada (ADR-0030)
1. Aceite do responsável para esta evidência e autorização escrita para ESTA identidade (OUI `FC4009`, serial TR-069 `…9122`, GPON `…D1EDA1A3`, PON 0/0/14, ONT-ID 11).
2. `bench-target-add` e entrada da ZTE em `bench.devices` do Edge (hoje ela só está em `bench.read_only_onus`).
3. Registro de capacidades por fabricante, modelo e firmware (o firmware da ZTE ainda não foi lido para a nuvem), com a evidência de cada operação.
4. Para o teste de banda: rota da WAN de serviço, origem no nó de teste, sonda de 3xx e aceite do risco, como na Huawei.

## Estado do Connection Request da ZTE (para o dossiê)
Funciona pelo ACS desde o retorno de 2026-10-31 22:22 UTC (HTTP 200 em 0,55 s); credencial por dispositivo gerada pelo ACS; antes, o Connection Request ficava sem resposta (timeout) enquanto a ZTE estava fora.
