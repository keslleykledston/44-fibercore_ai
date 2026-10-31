Feature: ONU Quick Inspector (FiberCore 2.2)
  Background:
    Given o operador esta autenticado em um tenant com permissao de inventario
    And os dados abaixo sao fixtures sinteticas

  Scenario: abrir e fechar sem perder a listagem
    Given a listagem ONU filtrada por POP Centro
    When seleciono uma ONU
    Then o resumo abre na direita
    And a listagem permanece filtrada por POP Centro
    When fecho o painel
    Then o foco retorna ao item acionador

  Scenario: diferenciar as fontes de verdade
    Given a OLT informa registro PON online
    And o GenieACS informa sem contato recente
    When abro o resumo
    Then vejo PON registrada
    And vejo ACS sem contato recente
    And nao vejo ONU offline causada apenas pelo ACS

  Scenario: trocar rapidamente
    When seleciono ONU A, B e C em sequencia
    And A responde depois de C
    Then visualizo apenas ONU C

  Scenario: cliente nao confirmado
    Given a associacao do cliente e conflituosa
    When abro o resumo
    Then nao vejo cliente confirmado
    And vejo aviso de vinculo em conflito

  Scenario: dispositivo sem template homologado
    Given o modelo da ONU e desconhecido
    When abro o resumo
    Then vejo miniatura generica com legenda
    And nenhum LED indica evidencias que nao existem

  Scenario: mobile acessivel
    Given visualizacao a 390x844
    When abro detalhes da ONU
    Then o painel opera como drawer modal de tela cheia
    And pressionar ESC fecha o painel e restaura o foco
