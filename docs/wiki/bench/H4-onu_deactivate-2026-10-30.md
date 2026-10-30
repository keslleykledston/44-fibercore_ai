# Evidência de manobra de bancada — H4 `onu_deactivate` (ciclo desativa → reativa) — 2026-10-30

Escopo: SOMENTE a ONU de bancada (`0/0/14`, ONT-ID 10) na OLT Huawei MA5608T (firmware MA5600V800R015C00). Sem credencial, IP, nome de cliente ou saída crua.

- **Hash da intenção:** `284fc46dcd5768873886dc3453287529e804baf4de67376446f58c519bddbe08` (job `68e7c250-08ba-44ca-97f5-c4e1c5d80cbc`, operação `onu_deactivate`, sem parâmetros)
- **Identidades observadas:** na mesma sessão CLI, antes de gastar o claim, o Edge leu (duas vezes) a ONU pela OLT: uma só ONU, F/S/P `0/0/14`, ONT-ID `10`, serial GPON `48575443E2247AA5` (igual ao do CPE no ACS e ao da lista local), `Run state: online`, `Config state: normal`, `Match state: match`, `Control flag: active`
- **Estado antes:** ONU online e ativa (`Control flag: active`, `Run state: online`)
- **Estado depois:** ONU de novo online e ativa, observada pela OLT na mesma sessão; o `deactivate` foi OBSERVADO (a ONU deixou de estar `active`/`online`) antes da reativação; a ONT não reiniciou (ACS: `_lastBoot` inalterado, 06:34:53Z, e ela seguiu informando); claim `DONE`; autorização `consumed`; sem trava de escrita
- **Resultado da restauração:** o próprio ciclo é a restauração: o Edge enviou `ont activate 14 10` SEMPRE depois do `deactivate` e só declarou sucesso com `Control flag: active` e `Run state: online` lidos de volta na OLT (`deactivated (observed), reactivated and online again`)
- **Versões:** Edge `0.7.2-lab-…`; firmware do CPE `V5R019C10S350`; OLT Huawei MA5608T, firmware MA5600V800R015C00
- **Aprovador:** o próprio solicitante, conta de serviço `isp_admin` de ensaio (`lab-bench-h4-…`, emenda "aprovação da bancada" do ADR-0030); autorização prévia `7e9ab27a-0e11-4138-b6a7-6468e4afa3ce` registrada pelo responsável (`--first-run`, janela 06:36:16–06:51:16 UTC)
- **Horário:** aprovação 06:36:43 UTC, despacho 06:36:53, job `SUCCEEDED` 06:37:23 UTC (duração ≈ 30 s)
- **Aceite do responsável:** PENDENTE — a registrar no chat da sessão antes de promover a `observed`

`ont deactivate` e `ont activate` não pedem confirmação nesta OLT (ver `H1-olt-caracterizacao-2026-10-30.md`); por isso o ciclo sempre reativa.
