# Homologação e matriz de testes FC25

## Piloto recomendado
Huawei MA5608T V800R015 (versão/patch/slot/cartão PON confirmados em laboratório). Somente habilitar capability no conjunto **exato** testado; outras R015 e MA5800 permanecem não certificadas até provas.

## Roteiro de laboratório
1. Inventariar OLT e perfis existentes com configurações anonimizadas; snapshot validado; nenhum perfil alterado.
2. Descoberta com uma ONU nova em PON de teste; validar SN, port, duplicidade e last-seen. Desabilitado auto-find? solicitar aprovação explícita para habilitar em laboratório.
3. ONU genuína vs SN incorreto e PON incorreta; ERP HubSoft ordem vinculada/sem ordem/contrato divergente.
4. Detectar modelo antes da autorização só se disponível; verificar portas reais e diferenças de firmware depois do registro.
5. Testar perfil Bridge Internet sobre VLAN de laboratório, DBA/TCONT/GEM/service port; comparar renderização preview vs equipamento; confirmar reutilização segura e perfil conflitante.
6. Job autorizar: precheck → apply → readback → ONU registrada/config normal/profile match → serviço passa tráfego de teste, PPPoE (se aplicável) e CPE ACS/USP se disponível. Não utilizar ONUs de assinantes reais.
7. Falhar OLT durante cada etapa; simular erro e timeout; `UNKNOWN/PARTIAL`, sem reexecução cega, sem exclusão de perfis usados.
8. Multi-tenant: acesso cruzado, token expirado, credenciais redigidas, approve/actor separado, auditoria, lock simultâneo.
9. Multi-OLT: piloto canário na primeira; se falhar, outras não serão alteradas; verificar fingerprint de ID físico diferente.
10. Qualidade: unit + contract + integration + Playwright screenshots 1440x900/390x844, artigos `/ajuda`; Codex PASS antes de qualquer piloto.

## Evidência obrigatória
Gravar OLT vendor/model/release/patch/card e ONU vendor/model/firmware, teste, operador, timestamp, comandos gerados revisados (redigidos), snapshot, diff, status verificado, caso de falha e rollback/remediação. Sem evidência: `unknown` e WRITE_BLOCKED.
