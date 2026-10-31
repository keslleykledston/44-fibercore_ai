# Help-by-construction — integridade com escopo existente

É obrigatório observar `DESIGN_SYSTEM_IOS_LIKE.md` e o adendo v2.1 do prompt mestre. Cada mudança visual integrada tem screenshot REAL da app, manual correspondente, acesso contextual e revisão.

## How-to previsto
Título: **Consultar rapidamente uma ONU sem sair da lista**  
Slug recomendado (verificar colisões): `consultar-resumo-onu`  
Rota: `/ajuda/<slug>`  
Estrutura: finalidade; selecionar ONU; identificar PON versus ACS; ler potência e frescor; verificar vínculo de cliente; abrir ONU 360°; fechar painel; problemas comuns (sem ACS, sem OLT, sem RX, sem permissão).

## Capturas finais da aplicação (não do preview)
- `docs/help/assets/onu-quick-inspector-desktop-1440x900.png` (dados de fixture)
- `docs/help/assets/onu-quick-inspector-mobile-390x844.png`
- variantes `stale`, `acs-unavailable`, `no-association`, `unknown-model` conforme necessário.
- Atualizar `docs/help/screenshot-manifest.yaml`, `docs/help/how-to/...`, `python tests/validate_help.py`.

## Atenção
Screenshots do preview do pacote são **somente protótipos de UX**. Nunca registrá-las como captura da aplicação funcional. Sanitizar serial/cliente e dados reais em imagens de documentação.
