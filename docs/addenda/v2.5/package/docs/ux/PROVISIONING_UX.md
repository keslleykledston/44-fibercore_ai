# UX — duas jornadas simples, progressive disclosure (iOS-like)

## Navegação existente (não criar área extra)
`Rede > ONUs pendentes` e `Rede > Templates de serviço`. Abrir drawer direito de ONU reutilizando componente v2.4, com miniatura SVG e status; da lista, botão primário **Autorizar** (somente quando elegível), secundários `Ver detalhes`, `Relacionar assinante`, `Atualizar leitura`.

## Lista de ONUs aguardando autorização
Tabela limpa: Detectada em | OLT / Porta PON | Serial | Fabricante provável (se justificado) | Assinante / OS | Condição | Ação.
Busca por serial/OLT/PON/OS, filtros `Nova`, `Sem correspondência`, `Elegível`, `Conflito`, `Antiga`. Não expor `offline` quando Edge está indisponível; usar `dados desatualizados`.
Drawer detalhe: linha do tempo, PON, possíveis duplicidades, binding HubSoft e evidências. Identidade incerta impede escrita.

## Wizard Autorizar ONU — até 4 etapas
1. **Identificar**: OLT/PON/SN, confirmação de evidências, vínculo HubSoft/OS (opcional, com política por ISP).
2. **Serviço**: escolher cartão `Internet Bridge` / `Internet Roteada` / `Internet + VoIP`, escolher plano e porta LAN. Preencher VLAN só se não herdada de template/OLT/OS. Avisar não suportado de forma clara.
3. **Conferir**: renderização abstrata de mudanças DBA/line/srv/service-port, perfis reutilizados/criados, risco, responsáveis, versão do template e OLT, conflitos, teste de pré-condições. `CLI gerada` acessível só a engenheiro, redigida e não editável.
4. **Solicitar autorização / Executar**: se perfil homologado e política autorizar, criar job; exibir status live, progress log redigido, verify; não confundir request accepted com sucesso.

## Wizard Construtor de Profiles — modelo preferido
**Cartões com opções guiadas + campos preenchidos automaticamente** são preferíveis a editor visual de fluxograma e a formulário extenso.
- Passo 1: `O que deseja entregar?` (Internet/VoIP/IPTV/Corporativo)
- Passo 2: `Como entregar?` (Bridge/ONU roteada, PPPoE/IPoE, tagged/untagged, portas de LAN)
- Passo 3: `Rede e velocidade` (VLAN/Stack, perfil de velocidade, ponto de controle QoS)
- Passo 4: `Onde usar?` (OLT(s), famílias PON, fabricantes/firmwares, ONTs compatíveis)
- Passo 5: `Revisão` (intent canônico, lista por OLT de profiles existentes/criados/modificados, risk/diff); salvar template versionado; publicar apenas com aprovação.
- Alternar `Configurações avançadas` abre DBA/T-CONT/GEM/QinQ/OMCI com ajuda contextual; campos condicionais por capability.
- Ao selecionar múltiplas OLTs, mostrar tabela por alvo com `compatível`, `exige ajuste`, `não homologado`, `conflito`, e checkbox explícito de cada OLT; default desmarcado.

## Estados e cópia
Sem discovery, sem homologação, dados antigos, sem porta LAN, modelo desconhecido, já autorizada, conflito SN, perfil ausente, migração de PON, job uncertain; explicar o motivo e próxima ação. Preservar arquitetura de `/ajuda`; screenshots via Playwright (1440x900 e 390x844), dados mascarados.

## Não criar telas poluídas
Resumo em 1 card de perfil de serviço, 1 de ONT/PON, 1 de revisão. Separar engenharia avançada por disclosure. Sem 15 abas ou 100 knobs de CLI para N1.
