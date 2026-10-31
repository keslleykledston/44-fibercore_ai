# H1 — evidência de vínculo ONU↔CPE — ZTE F670L — 2026-10-31 (SOMENTE LEITURA)

Escopo: **leitura**. Nenhuma escrita em equipamento, nenhum registro de alvo de bancada, nenhuma manobra. Complementa `H1-identificacao-zte-f670l-2026-10-31.md`, que deixou o vínculo **não confirmado**. Sem credencial, endereço, descrição de ONT ou dado de cliente. A posição na PON e os sufixos de serial aparecem porque são o próprio argumento do vínculo e já constam do ADR-0030 (emenda) e do H1 anterior da ZTE; nada além disso é versionado: a saída crua da OLT não foi impressa nem versionada, e só os campos listados abaixo foram extraídos.

## Autorização
O responsável, no chat da sessão em 2026-10-31: "a ONT zte é de bancada tbm" e, antes, "acesse a OLT e colete estes dados". Escopo: UMA ONT (ONT-ID 11 da PON 0/0/14), duas consultas de leitura, uma execução. Isto **não** é a autorização para cadastrar a ZTE como alvo de bancada (ver "Pendente").

## Como foi coletado
- Edge `0.1.0-lab-9ec5221` com a nova lista `bench.read_only_onus` (ONUs de bancada adicionais, **só para captura de leitura**; escopo de ONU com posição exata; nunca PON; não participa de manobra). Código revisado pelo Codex (3 rodadas, approve; `raw/314` a `raw/316`).
- Captura supervisionada (ADR-0032) de `onu.info` e `onu.register`, ONT-ID 11 da PON 0/0/14, na sessão de coleta de 2026-10-31 23:20 UTC, dentro do guarda de sessão única (intervalo de 15 min). Saída crua: arquivo 0600 no host do Edge (apaga sozinho em 24 h); a cópia local foi apagada com `shred` logo após a extração.

## Observado na OLT (somente o necessário ao argumento)
| Campo | Valor |
|---|---|
| Posição | PON `0/0/14`, ONT-ID `11` |
| Serial GPON | termina em `…D1EDA1A3` (igual ao do cache da coleta rotineira) |
| Tipo de equipamento registrado pela OLT | `F670LV9.0` |
| Estado na captura | online, autenticada por SN |
| Última queda | 2026-10-31 16:04:40 (−04:00) = 20:04:40 UTC, causa LOSi/LOBi |
| Última subida | 2026-10-31 16:05:47 (−04:00) = 20:05:47 UTC |
| Histórico de registro (`register-info`) | 2 entradas, ambas por SN e tipo `F670LV9.0`; a mais antiga em 2026-10-30 22:08 (−04:00) |
| Descrição da ONT | existe (**não impressa**) |

Distância, estado de gerenciamento e demais campos extraídos foram omitidos deste arquivo por não serem necessários ao argumento.

## Origem e semântica dos horários
- **OLT:** os horários vêm da saída da OLT com o deslocamento −04:00 que ela mesma informa; o relógio da OLT **não foi conferido** contra o do ACS (existe a consulta `olt.time`, não executada), então **não há limite de incerteza conhecido** entre os dois relógios e os horários de OLT e ACS não são comparados quantitativamente neste documento.
- **ACS (UTC):** `_lastInform` e o `1 BOOT` são o instante em que o **ACS recebeu** o Inform, não o instante em que o evento ocorreu na ZTE. O uptime (8.542 s) é um valor lido pela ONT e guardado pelo ACS às 22:33:42 UTC (instante da gravação no cache), com resolução de 1 s e sem confirmação de qual contador a ZTE usa (sistema ou aplicação TR-069).

## Leitura da evidência (SUGESTIVA, não conclusiva)
- **Compatível, mas não independente nem exclusiva:** a OLT registra, em 0/0/14 ID 11, uma ONT de tipo `F670LV9.0` com serial GPON terminado em `…D1EDA1A3`; o ACS tem um dispositivo ZTE F670L e o seu SSID contém esse trecho. Limites: (a) o **modelo não distingue** esta ONT de outras F670L; (b) o **SSID de fábrica é derivado do próprio serial**, então não é uma segunda fonte independente do mesmo fato; (c) o ACS não expõe o GPON SN completo, logo **não há igualdade completa de serial** entre OLT e CPE.
- **Linha do tempo: apenas qualitativa.** A OLT registrou uma queda e a volta da ONT por volta de 20:04–20:05 UTC (causa LOSi/LOBi); no ACS, a ZTE deixou de informar logo depois (último Inform recebido às 20:08 UTC) e o seguinte só chegou às 22:22 UTC, com um `1 BOOT` que parece atrasado (entregue quando a ZTE voltou a alcançar o ACS). Isso é **compatível** com a mesma ocorrência, mas, **como o desvio entre o relógio da OLT e o do ACS não é conhecido, não calculo diferenças em minutos nem fixo um horário de boot**: o uptime lido (8.542 s às 22:33 UTC) não foi usado para inferir um boot. O reinício das 22:22 UTC **não aparece como queda na OLT** e não deve ser tomado como o reboot observado.
- **Causa da queda de 20:04 UTC: não verificada** (LOSi/LOBi é perda de sinal óptico; pode ser fibra, conector ou o equipamento).

## Conclusão
O vínculo é **inferido** e permanece **não confirmado e não registrado**: há indícios coincidentes, nenhuma prova independente. Para confirmar: reinício acompanhado da ZTE com a ONT 11 observada offline→online na OLT (e o horário conferido contra o relógio da OLT), ou leitura do GPON SN completo no próprio equipamento (etiqueta ou interface). Nada foi registrado no FiberCore.

## Pendente antes de qualquer alvo de bancada (ADR-0030)
1. Confirmação do vínculo (ver Conclusão) e autorização escrita do responsável para ESTA identidade. A identidade completa (OUI, serial TR-069 e GPON, posição) fica no registro do owner CLI e na configuração local do Edge, não neste arquivo.
2. `bench-target-add` e entrada da ZTE em `bench.devices` do Edge (hoje ela só está em `bench.read_only_onus`).
3. Registro de capacidades por fabricante, modelo e firmware (o firmware da ZTE ainda não foi lido para a nuvem), com a evidência de cada operação.
4. Para o teste de banda: rota da WAN de serviço, origem no nó de teste, sonda de 3xx e aceite do risco, como na Huawei.

## Estado do Connection Request da ZTE (para o dossiê)
Funciona pelo ACS desde o retorno de 2026-10-31 22:22 UTC (HTTP 200 em 0,55 s); credencial por dispositivo gerada pelo ACS; antes, o Connection Request ficava sem resposta (timeout) enquanto a ZTE estava fora.
