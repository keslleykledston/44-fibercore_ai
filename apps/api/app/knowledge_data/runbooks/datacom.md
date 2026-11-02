# Runbook DATACOM — consulta, diagnóstico e homologação

**Escopo:** não altera configurações; **estado:** referência documentada, NÃO execução homologada no FiberCore. **Fonte(s):** DC-01, DC-02, DC-03 (`knowledge/sources/registry.json`).

## Pré-check (somente leitura)
Identificar plataforma exata, DmOS/firmware e interface. Capturar commit mode.

## Consulta e diagnóstico
Consultar discovered-onus e lista ONU da porta GPON real.

## Diretriz de alteração futura
Só então mapear bandwidth/line/service-profile/ONU com dry-run e commit aprovado.

## Passo padrão para suporte NOC
1. Confirmar equipamento/POP/endereço de gestão e credencial do cofre.
2. Ler identidade: firmware, card/inventário, timestamp, latência, dispositivo respondendo?
3. Ler estado **físico PON** (`admin`, `oper`, `optic`) e contagem ONU (`online`, `offline`, `unknown`) separadamente.
4. Se telemetria expirar, marcar `STALE/UNKNOWN`, nunca fabricar um `DOWN`.
5. Analisar alarmes, sinal óptico e eventos só se o driver oferecer essas capacidades.
6. Registrar `correlation_id`, output sanitizado, source_id e evidências; escalar sem alteração.

## Critérios para sair de pesquisa
- [ ] Documento correspondente ao `firmware/build` real
- [ ] Comando exato sem escrita e prompt correto capturados em bancada
- [ ] Saída sanitizada e parser golden com caso negativo
- [ ] Timeout, paginação e falha de transporte cobertos
- [ ] Valores normalizados conferidos com NMS/CLI
- [ ] Auditoria e redaction de ONU/cliente aprovadas
