# Runbook do responsável — H4 `onu_reset` e `onu_deactivate` na ONU de bancada (ADR-0030)

Escopo: SOMENTE a ONU de bancada (`0/0/14`, ONT-ID `10`, ver `H1-olt-caracterizacao-2026-10-30.md`). Porta e ONT-ID vêm da configuração LOCAL do Edge (`bench.olt`); a nuvem não os envia. `all` e `graceful` não existem na lista de comandos. A ONU de bancada fica fora do ar por 1 a 3 minutos (reset) ou durante a desativação (alguns segundos a 30 s) — avise quem usa a ONT.

## O que cada operação faz (uma sessão CLI, sob o guard da OLT)
1. `enable` → `display ont info by-sn <serial GPON>`: tem de ser UMA ONU, `0/0/14`, ONT-ID 10, serial igual ao configurado, `online`, `normal`, `match`, `active`; senão nada é enviado.
2. `config` → `interface gpon 0/0` → (o Edge só gasta o ritmo e a sua autorização aqui, depois da identidade confirmada).
3. `onu_reset`: `ont reset 14 10` e observa a ONU voltar `online` com novo `Last up time`.
4. `onu_deactivate`: `ont deactivate 14 10`, observa que saiu do ar (até 30 s), **reativa sempre** (`ont activate 14 10`) e observa `online` e `active`.

## Pré-condições
- Edge com `onu_reset`/`onu_deactivate` em `allowed_operations` e `bench.olt` (nome da OLT = uma das `olts` em CLI, `frame/slot/port/ont_id`, `gpon_serial` igual ao serial do dispositivo de bancada; `min_gap_seconds` ≥ 60 durante a homologação).
- Registro (por operação): `capability-set <tenant> huawei MA5608T MA5600V800R015C00 olt <operação> supported identified --evidence <arquivo> --verified-at <agora>` (o perfil é o da OLT).
- Migrações até a 0022 e API com o PR do H4. ONU e CPE com vínculo `confirmed`.
- Autorização: `bench-authorize <tenant> <operação> <cpe da bancada> --from ... --to ... --by "Seu Nome" [--first-run]`.

## Se algo sair do esperado
- Resultado `FAILED`/`UNKNOWN`: alvo travado. Antes do `bench-unlock`, olhar a ONU na OLT (`display ont info 14 10`). Se ela ficou **desativada**: `ont activate 14 10` no modo `interface gpon 0/0`.
- O sinal "a ONU pode ter ficado desativada" vem no detalhe do job.
