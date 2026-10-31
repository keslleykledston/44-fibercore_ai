# User stories / Given-When-Then

**US-01** Como NOC, ao selecionar uma ONU na lista quero identificar sua situação sem abandonar a tela. **Aceite:** 1 clique abre à direita; lista/filtros preservados; selecionada destacada; 360° separado.

**US-02** Como suporte, quero diferenciar PON online de ACS sem contato. **Aceite:** estado PON permanece `online` e ACS `stale/unavailable` independente; nenhum LED LOS vermelho sem observação real.

**US-03** Como N2, quero confiar na potência e saber quando foi coletada. **Aceite:** valor numérico com dBm, source, observed_at e stale; ausente mostrado como `Não disponível`; cor somente se alerta/limiar validado na plataforma.

**US-04** Como analista, ao trocar rapidamente 20 ONUs quero visualizar somente a selecionada. **Aceite:** cancelar/ignorar respostas antigas; sem flash de cliente de outra ONU; não vazar tenant.

**US-05** Como gestor de múltiplos ISPs quero isolamento. **Aceite:** backend aplica RLS/permissões; tenant A não observa ONU/cliente B; sem info em logs/cache por seleção inválida.

**US-06** Como usuário mobile quero consultar com acessibilidade. **Aceite:** overlay modal, foco contido, ESC/fechar, botão de 44px, scroll, retorna foco, sem horizontal scroll.

**US-07** Como operador de equipamento desconhecido, quero saber o status sem imagem errada. **Aceite:** miniatura genérica + rótulo `Representação genérica` e nenhuma afirmação de LEDs reais.

**US-08** Como operador preciso do histórico detalhado. **Aceite:** CTA leva para 360° canônica se rota existir, com retorno seguro ao contexto; se ausente, não inventar rota.

**US-09** Como técnico quero dados mesmo se ERP ou ACS estiverem fora. **Aceite:** OLT continua disponível; cada integração com estado próprio; painel não fica em erro total por uma dependência opcional.

**US-10** Como responsável de segurança quero ações remotas sob controle. **Aceite:** sem botões write adicionados; CTA de investigação somente se capacidade existente e RBAC; nada executa automaticamente.

**US-11** Como usuário com redução de movimento, não quero LEDs piscando. **Aceite:** `prefers-reduced-motion` desativa microanimações e informações continuam legíveis.

**US-12** Como operador, uma ausência de coleta não é falha da ONU. **Aceite:** campos `unknown` e `stale` explícitos, timestamp e source. Sem colorir verde/laranja/vermelho por suposições.
