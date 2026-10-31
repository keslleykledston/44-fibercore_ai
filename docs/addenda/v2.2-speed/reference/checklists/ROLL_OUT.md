# Checklist operacional (preencher antes do deploy)

- [ ] Estado atual do repo mapeado e plano de gaps aprovado
- [ ] Branch/PR pequenos, sem refatorar plataforma
- [ ] Adapter GenieACS usa **somente Edge outbound**
- [ ] Root Device/IGD e interface WAN de serviço confirmados
- [ ] Capability Registry atualizado por modelo+firmware
- [ ] RBAC e isolamento tenant testados
- [ ] Test Node Core alcançável via WAN serviço, GET e PUT
- [ ] Test Node Internet (se ativado) fora do core e aprovado
- [ ] Firewall/ACL, limite tamanho e simultaneidade configurados
- [ ] Sem senha/token no log/ACS URL
- [ ] Tarefas HTTP 200 e 202 do GenieACS simuladas
- [ ] Resultado stale e ausência Inform simulados
- [ ] UI drawer responsivo, acessível, sem valores fictícios
- [ ] Teste piloto real contra Core e Internet, sem impacto anormal
- [ ] How-to e screenshots reais publicados em /ajuda
- [ ] Feature flag OFF até aprovação do NOC
- [ ] Codex PASS sem BLOCK; rollback documentado
- [ ] Operador responsável autorizou ativação
