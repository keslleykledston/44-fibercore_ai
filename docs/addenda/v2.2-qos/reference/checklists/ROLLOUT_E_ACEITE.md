# Checklist implantação incremental

- [ ] Pacote base SD-001 disponível; hash conferido ou diferenças justificadas.
- [ ] Diagnóstico no repo real inventariado, lacunas escritas antes do código.
- [ ] RÁPIDO e COMPLETO subordinados ao RBAC do NOC, multitenant validado.
- [ ] Fake GenieACS cobre `200`, `202`, timeout, inform atrasado, objeto ausente e erro CPE.
- [ ] WAN de serviço homologada; bridge e gestão-only corretamente bloqueadas.
- [ ] Sem variáveis secretas em URL/HTML/prompts/log; no browser não há acesso direto ao ACS.
- [ ] Onboarding de pelo menos um perfil roteado; uma ONU bridge verificada.
- [ ] Sem alteração de política em OLT/BNG, provisionamento ou config Wi-Fi.
- [ ] UI apresentada em sidebar existente; help center com capturas da aplicação real.
- [ ] Changelog e compatibilidade por firmware registrados.
- [ ] Flag OFF por padrão; ativação restrita aprovada; rollback por flag testado.
