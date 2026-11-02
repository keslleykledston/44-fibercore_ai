# UX — Profile Expert Editor (Lovable + Claude Code)

## Navegação
`Rede > Profiles > Catálogo > [template] > Modo Especialista` e `Rede > OLTs > [OLT] > Profiles existentes > [profile] > Importar referência`. Um único Profile Studio, **não um segundo produto**. Sidebar direito do v2.5 pode abrir resumo do profile e ocorrências, com expansão para editor completo.

## Layout minimalista — Desktop
- **Cabeçalho fixo:** `OLT / Profile / Revisão`, estado `DRAFT`, status dados `fresco/stale`, opção `Voltar ao assistido`.
- **Coluna esquerda (~25%):** fontes: `Profile da OLT`, `Template do catálogo`, `Nova variante`, versões, uso/ONUs vinculadas, hora coleta. Busca rápida e filtros.
- **Centro (~45%):** formulário semântico agrupado em acordeões: Geral, Tecnologia/DBA, T-CONT/GEM, VLAN/Service-Port, QoS, Portas ONU, Recursos específicos. Os campos editáveis usam controle apropriado: dropdown enumerado, campos numéricos com unidades, chips de VLAN, tabelas pequenas, seleção de objetos dependentes. Labels técnicos com tooltip.
- **Direita (~30%):** diff semantic (antes→depois) e impacto por alvo, sem CLI por padrão. `Mostrar código gerado (somente leitura)` exclusivo N3; a CLI não pode ser copiada para execução direta pelo sistema.
- **Rodapé fixo:** Salvar rascunho; Comparar; Simular; Solicitar publicação. Nunca botão simples “Aplicar em todas as OLTs”.

## Mobile
- Uma coluna, navegação por abas `Fonte | Editar | Diferenças`, sem tabelas gigantes. Alterações de alto risco requerem confirmação e podem restringir mobile por política.

## Componentes
`NativeProfilePicker`, `ProfileSnapshotHeader`, `ImmutableSourceNotice`, `SemanticDiffViewer`, `CapabilityField`, `ReferenceImpactCard`, `OLTTargetMatrix`, `DraftVersionHistory`, `ValidationErrors`, `PreviewJobDrawer`, `ApprovalTimeline`.

## Textos e estados
- `Importar como referência (não altera OLT)`
- `Criar variante` / `Reutilizar exatamente` / `Vincular existente` / `Planejar migração (fluxo separado)`
- `Profile usado por 126 ONUs — edição no local bloqueada`
- `Não foi possível confirmar se há ONUs utilizando este profile — somente clone`
- `Parâmetro não suportado pelo firmware selecionado`
- `O profile foi alterado na OLT após sua importação. Atualize a comparação.`
- `Nenhuma alteração será enviada ao equipamento nesta etapa`

## Casos críticos de UX
Loading, parcial, Edge indisponível, dados antigos, conflito ID/nome, campo não observável, perfil vazio, diferença de unidades, comportamento vendor-specific, drift, approval expirado, implantação parcial, perda de conectividade; em cada caso indicar próxima ação.

## Ajuda integrada
Atualizar `/ajuda`: importar profile, clonar, comparar, editar DBA/T-CONT/GEM, validar VLAN, publicar e planejar migração. Capturas reais Playwright desktop 1440x900 e mobile 390x844, com fixtures, dados fictícios e sem credenciais.

## Edição estruturada em YAML/JSON (opção para N3)
Oferecer alternância `Formulário | YAML/JSON tipado` mostrando **a mesma estrutura canônica**, com validação ao digitar, realce de campos não suportados, diff e sincronização bidirecional com o formulário. **Não é editor de CLI** e não aceita instruções de shell. O contrato `expert-profile-draft.schema.json` é base; validações por driver, firmware e regras cruzadas ocorrem no backend. CLI do fabricante, quando gerada, permanece apenas em uma terceira visualização `Comandos previstos (somente leitura)`, sob RBAC.

Quando o engenheiro importar um profile de formato legado, o driver deve interpretar apenas sintaxe reconhecida; linhas desconhecidas são preservadas **como texto de referência sanitizado**, com aviso `não traduzido` e bloqueio de equivalência/aplicação. Não descartar silenciosamente essas linhas.
