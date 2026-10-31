# PRD — ONT Configuration Manager (v2.4)
## Problema / oportunidade
O operador consegue consultar a ONU/ONT, mas ações comuns exigem consoles diferentes ou parâmetros TR-069 não amigáveis. O FiberCore fornecerá um **formulário condicionado às capacidades reais** do equipamento. Nenhuma opção inexistente ou sem permissão aparece como ativa.

## Personas e escopo
- Atendimento/NOC N1: consulta, diagnóstico guiado, solicitar troca SSID; senha só via política e autorização explícita.
- NOC N2/Engenharia: Wi-Fi, LAN, WAN e ações técnicas homologadas com preview/aprovação.
- ISP Admin: define política por tenant, grupos de modelo, janela, risco e limites de alteração.
- Auditor: trilha completa sem acesso a segredos.
- Campo: consulta e roteiro de assistência; não ganha escrita por estar no local.

## Configurações/estados
| Grupo | Capabilities propostas | Etapa | Risco inicial |
|---|---|---|---|
| Identidade/Status | Modelo, serial, firmware, portas LAN, últimas fontes, disponibilidade | P0 leitura | R0 |
| Wi-Fi básico | `wifi.ssid.read/write`, `wifi.enabled.read/write`, por SSID/rádio resolvidos | P0 | R1/R2 |
| Wi-Fi segurança | `wifi.password.rotate`, segurança WPA quando homologada | P1 | R2 |
| Wi-Fi avançado | `wifi.channel`, `wifi.bandwidth`, `wifi.tx_power`, band steering, guest, isolation | P1 | R2 |
| LAN básico | `lan.ipv4_address`, `lan.netmask`, `lan.dhcp_enabled`, `lan.dhcp_pool`, `lan.dns` | P1 | R3 |
| WAN | `wan.pppoe`, `wan.ipoe`, `wan.vlan`, `wan.nat`, `wan.ipv6` | P2 | R3 |
| Óptica | `optical.rx_dbm`, `optical.tx_dbm`, LOS, temperatura, tensão, OLT PON binding | P0 somente leitura | R0 |
| Diagnóstico | reboot, ping, traceroute, speed test se realmente implementado pelo CPE/ACS/USP | P0/P1 | R1/R2 |
| Gestão | backup/export e atualização firmware por perfil, homologação e canário | P2 | R3 |

**Riscos parametrizáveis**: defaults conservadores; configuração final por operação, firmware, dispositivo, impacto e tenant. Ações LAN/WAN devem ser bloqueadas sem plano explícito de recuperação out-of-band e operador N2.

## UX
- **Sidebar direito recolhível** integrado ao Subscriber 360 e ao inventário ONU: cabeçalho com miniatura vetorial do modelo quando identificada, estado e timestamp; abas **Resumo | Wi-Fi | LAN | Avançado | Histórico**. Óptica/diagnóstico podem ficar em Resumo/aba conforme estrutura real.
- Padrão iOS-like original K3G, responsivo, mínimo ruído; primeiro mostrar status/frescor/fonte e uma ação primária. Formulário usa schema retornado pela API, não telas hardcoded por fabricante.
- Se não houver capacidade: `Não suportado pelo equipamento`/`Não homologado`/`Leitura indisponível`, claramente distintos. Campo `read-only` nunca ganha botão Salvar.
- `Editar` abre formulário com versão e valor observados, `Pré-visualizar` mostra **diff sanitizado**, risco e perda possível de conectividade. Submissão gera job assíncrono; UI mostra `Aguardando dispositivo`, `Verificando`, `Aplicado e confirmado`, `Falhou`, `Resultado incerto`.
- Password write é **one-way**: nunca expor segredo atual, UI possui novo segredo, confirmação, requisito de complexidade e visibilidade local temporária; backend armazena em secret vault com TTL, sem devolver plaintext.

## Jornada principal
Busca assinante (HubSoft quando integrado) → Subscriber 360 → miniatura ONT/sidebar direito → identificar `CPE binding` (TR-069 ou USP) → descobrir capacidades → selecionar rádio/SSID/instância → editar → preview da alteração → confirmar solicitação → aprovação segundo política → dispatch Edge/adapter → task ACS ou USP → pós-check independente → audit e resultado.

## Casos de erro
- ACS/USP offline: dados stale; bloquear escrita, permitir diagnóstico do conector.
- Dispositivo dual-stack: proibido escrever o mesmo escopo por CWMP e USP ao mesmo tempo; lock compartilhado por `physical_device_id + capability_scope`.
- Firmware alterado após preview: invalidar aprovação e novo discovery.
- ONT em modo Bridge sem Wi-Fi: não fabricar aba Wi-Fi nem parâmetros.
- Nenhum SSID: aba read-only com explicação; não assumir instância `.1`.
- `HTTP 202` GenieACS: **tarefa enfileirada**, não sucesso. Mesmo HTTP 200 não dispensa pós-verificação de valores observados.
- Mudança de LAN/WAN pode derrubar ACS; suspender retry, marcar `unknown` e abrir recuperação guiada.
- Optics RX/TX nunca recebe setter arbitrário.

## Fora de escopo
Editor de TR-069 raw path ou shell para usuário final; BGP/DHCP massivo; payload genérico injetável; firmware bulk sem homologação; cópia do dashboard GenieACS; inferir 100% compatibilidade pela marca; envio de senhas para LLM.

## Métricas
Tempo da tarefa N1, tempo do preview, sucesso **verificado** por capacidade+modelo+firmware, intervalo `queued→confirmed`, falhas que causam perda de conectividade, cobertura de perfis homologados e taxa de documentos help sincronizados. Medir baselines antes de definir SLA.
