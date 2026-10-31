# Plano de entrega com 3 PRs pequenos

## PR 0: Descoberta (sem alterar produção)
Inspecionar arquitetura real (GenieACS adapter, Edge connector, Capability Registry, job engine, RBAC, drawer, banco, testes e help center). Produzir `CURRENT_STATE.md` e `GAP_MAP.md` com caminhos reais, decision record e diff planejado. Evitar reinventar serviços do FiberCore.

## PR 1: Backend e execução
- Pegar estruturas existentes, adicionar provider TR143 e descoberta.
- Conectar através de Edge outbound existente, sem abrir NBI publicamente.
- Registrar jobs + resultados no datastore já usado; concorrência e RBAC.
- Implementar adapter Device:2 / IGD:1, validação, freshness, timeout e resultado parcial.
- Criar/validar endpoint Core disponível. Internet apenas se test node externo aprovado estiver pronto.
- Testes de integração e mock/fake NBI.

## PR 2: UX, homologação e documentação
- Adicionar seção Teste de banda ao drawer atual.
- Dados reais pela API, estados mínimos, sem número falso.
- Homologar 1 modelo/firmware com GET/PUT e WAN serviço.
- Capturas reais de disponibilidade, execução, sucesso, parcial e erro; criar how-to `/ajuda`.
- Release notes + métricas + feature flag OFF por padrão até aprovação.

## Risco principal
Não há garantia de que a ONT execute o teste pela WAN desejada mesmo se os parâmetros constarem no GenieACS. A homologação deve confirmar rota, VLAN, perfil e que a CPU do CPE não é limitante. Não escrever interfaces genéricas sem detecção/validação.

## Pronto para ativação quando
- Endpoint de teste tem capacidade validada.
- ACL/firewall habilitados.
- Permissão e escopo tenant validados.
- Piloto demonstrado com registros reais.
- Fallback completo da UI e `feature flag` funcionais.
- Codex aprovou, operador responsável autoriza deploy.

## Integração opcional futura
TR-471/OB-UDPST, UPnP/adapter de fabricante, probes em LAN, teste agendado, jitter/loss e correlação PON/BNG; documentar como backlog, não construir neste incremento.
