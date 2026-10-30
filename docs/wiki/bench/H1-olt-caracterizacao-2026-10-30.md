# H1 (lado OLT) — caracterização somente leitura da ONU de bancada (ADR-0030) — 2026-10-30

UMA sessão CLI supervisionada na OLT Huawei MA5608T (firmware MA5600V800R015), SOMENTE leitura e ajuda (`?`), com allowlist exata de comandos, chave de host pinada, reserva do guard da OLT renovada antes (o Edge esperou) e nenhuma escrita. Sem credencial, IP ou saída crua neste arquivo.

## Identidade confirmada na OLT
- Consulta `display ont info by-sn <serial GPON de 16 hex>` devolveu **uma** ONU: posição `0/0/14`, **ONT-ID 10**, `Run state: online`, `Config state: normal`, `Match state: match`, `Control flag: active`, `Authentic type: SN-auth`, SN = `HWTC-E2247AA5` (os 16 hex são `48575443` = "HWTC" + `E2247AA5`).
- Isso fecha a igualdade do ADR-0030: o serial GPON da ONU é **exatamente** o serial do CPE no ACS (`48575443E2247AA5`), e não só o sufixo. O H1 anterior só tinha o sufixo.
- O campo "Last down cause" da ONU mostra `ONT is reset by ONT command` — o efeito dos reboots do H2 visto pela OLT (a hora do relógio da OLT está ~7 min atrás da nossa).

## Sintaxe dos comandos de manobra (só ajuda `?`, nada executado), modo `interface gpon 0/0`
- `ont reset ?` → `graceful` | `portid<U><0,15>`; `ont reset <porta> ?` → `all` | `ontid<U><0,127>`.
- `ont deactivate <porta> ?` e `ont activate <porta> ?` → `all` | `ontid<U><0,127>`.
- **Perigo:** o argumento `all` atinge TODAS as ONUs da porta. Nenhum comando de manobra pode ter `all` nem `graceful`; porta e ONT-ID são inteiros vindos da configuração LOCAL do Edge, nunca da nuvem.

## Estado de partida para a H4
`0/0/14`, ONT-ID `10`, online, `Config state: normal`.
