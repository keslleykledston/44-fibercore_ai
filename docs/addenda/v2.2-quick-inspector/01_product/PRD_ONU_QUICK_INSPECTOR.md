# PRD — ONU Quick Inspector (adendo UI FiberCore 2.2)

## Problema
Em listas de ONUs e árvores OLT/PON, o operador hoje/na UX planejada precisa mudar de contexto para verificar rapidamente o estado da ONU. Queremos que a consulta da situação e o acesso ao diagnóstico detalhado ocorram com mínimo atrito.

## Objetivo
Exibir, no sidebar direito recolhível e reutilizável, **identidade + miniatura + estado verificável + cliente/associação + métricas essenciais + ação de aprofundar**, sem duplicar a Visão 360°.

## Personas
- NOC N1: identifica ONU, estado PON, ACS, última coleta e cliente vinculado sem navegar.
- NOC N2/Engenharia: confirma RX, origem e qualidade do dado e abre 360°.
- Suporte: identifica cliente somente se relação confiável e autorizado; evita diagnóstico falso.

## Hierarquia da interface (ordem fixa, capacidades opcionais)
1. Cabeçalho: nome/serial, fabricante/modelo, estado principal, fechar, link de ajuda.
2. Miniatura SVG (compacta, passiva; LEDs apenas se capability homologada). Sem animação excessiva.
3. Linha de evidência: `PON: ...` | `ACS: ...` em campos separados com origem/atualização.
4. Metadados: `OLT / PON`, `ONU ID` se disponível, `RX ONU` se disponível; sem valores inventados.
5. Vínculo: cliente/contrato **somente se permitido e confiável**, senão etiqueta de não associado/conflito.
6. Ações: `Abrir Visão 360°` (principal); `Investigar` (secundária e condicional); ações remotas NÃO entram aqui.
7. Indicador de frescor detalhado e estado de indisponibilidade.

## Fluxos
- F1 Lista: selecionar ONU -> drawer -> selecionar outra -> conteúdo troca -> fechar -> foco retorna à linha.
- F2 OLT/PON: selecionar ONU na árvore -> drawer sem perder expansão da árvore.
- F3 Incidente: abrir ONU vinculada, preservando incidente e breadcrumb; fechar -> continua incidente.
- F4 ONU 360°: clicar CTA -> rota canônica existente com retorno seguro ao contexto, se essa capacidade existir.
- F5 Sem dados: shell/identidade disponível, demais seções com `Sem coleta` / `Não disponível` e ação de 360° quando autorizada.
- F6 Indisponibilidade: quando ACS não responde, não mudar estado físico PON para `Offline`.

## Requisitos funcionais
R1 Seleção controlada por `selectedOnuId` e namespace de tenant; requests concorrentes da seleção anterior não podem sobrescrever seleção nova.  
R2 Estado do drawer pode ser preservado durante troca entre listas/visões da mesma sessão, mas nunca vazar tenant.  
R3 Caber em 1440x900 e 390x844 sem rolagem horizontal; conteúdo interno scrollável, header/ação acessíveis.  
R4 Reuso de componentes/tokens; modo claro/escuro; foco/teclado/leitor de tela.  
R5 Dados com source, `observed_at`, `collected_at` e frescor por campo quando disponível.  
R6 Flags e estados confiáveis; não atribuir PON status por LED animado inferido.  
R7 Preservar link, busca, filtro e rolagem da tela-mãe (quando suportados).  
R8 Não introduzir dependência forte de ERP/ACS/USP para renderizar resumo da OLT.  
R9 Segurança server-side de tenant e permissão de acesso a cliente/identificadores.  
R10 Feature flag habilitável/desabilitável com rollback sem migração.

## Métricas UX propostas (metas, não resultados)
- Informação essencial perceptível em até 5s após renderização.
- 1 clique para abrir detalhes; 1 clique para selecionar outra ONU; 1 clique para fechar.
- ≤3 interações da busca até o contexto de diagnóstico, quando a rota existir.
- Zero falsos `ONU offline` provocados exclusivamente por indisponibilidade ACS.

## Não metas
Não construir biblioteca visual multivendor completa, automações, nova API por conveniência, LLM novo, gráfico de tráfego ou painel de configuração Wi-Fi nesta entrega.
