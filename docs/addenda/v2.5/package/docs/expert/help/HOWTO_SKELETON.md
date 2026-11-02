# How-to: Ajustar um profile existente com o Expert Editor

Estado: DRAFT (atualizar com screenshots reais apenas depois da UI implementada)

1. Acesse `Rede > Profiles > Modo Especialista`.
2. Selecione OLT e profile; confira origem, firmware e horário da leitura.
3. Clique `Importar como referência`; um snapshot imutável será salvo.
4. Use `Criar variante` para preservar o original; selecione o template FiberCore de destino.
5. Ajuste apenas campos habilitados pelo driver, por exemplo VLAN, porta LAN, DBA ou GEM.
6. Clique `Comparar` e revise riscos e impacto sobre ONUs que usam o perfil.
7. Clique `Simular por OLT`; sem mudanças no equipamento.
8. Salve rascunho e solicite publicação; execução somente após gates e aprovação.
9. Verifique jobs e evidências, `PARTIAL/UNKNOWN` exige reconciliação.

Capturas a produzir após implementação: `expert-import-desktop.png`, `expert-diff-desktop.png`, `expert-preview-mobile.png` em 1440×900 e 390×844. Não inventar screenshots.
