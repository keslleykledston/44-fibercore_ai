# H2 — Captura: lista de ONUs não provisionadas (Datacom DmOS e Intelbras 8820)

Data: 2026-11-15 | Somente leitura | Sanitizado (sem IP, hostname, serial ou credencial)

Objetivo: achar o comando que lista as ONUs descobertas e ainda não autorizadas, para estender a fila `rede/pendentes` (ADR-0054/0055) além da Huawei.

## Datacom DmOS (4 OLTs: WA TELECOM x2, GL CONNECT, ARAUJO)
- Ajuda da PON (já em H1): `show interface gpon 1/1/1 ?` lista `discovered-onus`.
- Comando: `show interface gpon <slot/porta-pon> discovered-onus | nomore` (por PON; o sufixo ` | nomore` já é aceito pelo `SafeCommand`).
- Resposta com a lista vazia, nas quatro OLTs, em `1/1/1` e `1/1/2`: uma linha `% No entries found.`
- **Layout COM entradas: não observado.** Nenhuma OLT tinha ONU pendente.

## Intelbras 8820 (ASANET, Telnet)
- `onu ?` lista `show`, `status`, `find`, `clear`, `delete`, `reboot`, etc.; `onu show ?` aceita `auto`, `gpon`, `refresh` e `<enter>`.
- Comando de leitura: `onu show` (sem argumento). **Não usar `refresh`** (atualiza a lista de descobertas na OLT).
- A saída, por link GPON (1 a 8): `Free slots in GPON Link N:` + grade de slots livres + `Discovered serial numbers` com o cabeçalho `sernoID   Vendor  Serial Number   Model       Time Discovered`.
- Todos os 8 links com a tabela vazia (só o cabeçalho). A saída traz antes a linha `The OLT system is processing, waiting to execute command...` (ruído já tratado por `IntelbrasNoise`).
- **Layout das linhas de ONU: não observado** (só o cabeçalho).

## Conclusão
Os dois comandos existem e funcionam em leitura. Falta uma ONU realmente pendente em cada fabricante para fixar o formato das linhas. Sem isso, um parser seria chute, e a regra do projeto é falhar fechado. Quando houver uma ONU pendente, capturar `show interface gpon <pon> discovered-onus | nomore` (Datacom) e `onu show` (Intelbras), sanitizar e só então escrever o driver.
