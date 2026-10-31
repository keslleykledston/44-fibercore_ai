> **Referência recebida (2026-10-31), mantida como veio. Onde divergir do repositório, vale `docs/addenda/v2.2-qos/{CURRENT_STATE,GAP_MAP,IMPLEMENTATION_PLAN}.md` e a tabela de divergências em `docs/addenda/v2.2-qos/README.md` (lock compartilhado, ADR-0030, WAN de serviço, tabela de suite).**

# Segurança, capacidade de rede e privacidade

## Reuso da política atual
- RBAC/tenants/audit/feature flag **existentes**; criar somente escopos se não existirem: `diagnostics.quality.read`, `diagnostics.quality.run.quick`, `diagnostics.quality.run.full` (mapear aos papéis atuais). Quem pode executar completo deve também estar autorizado ao SD-001.
- Nenhum IP/URL arbitrário fornecido pelo usuário ao CPE: lista de alvos autorizados por tenant e perfil, com bloqueio de SSRF e destinos privados indevidos; CORE pode ser privado **aprovado**, não qualquer RFC1918. DNS só hostname cadastrado. Traceroute somente destino autorizado.
- Nenhum endpoint NBI/Mongo público; trafegar Edge outbound existente. Assinaturas/auth do Edge e logs correlacionados a `tenantId`, `runId`, `deviceId`.
- Não ler/exportar credenciais Wi-Fi, senha PPP, ACL, MAC/BSSID/SSID da rede vizinha quando não indispensável; mascarar/logar somente agregados. Limitar retenção ao padrão atual.
- Não usar execução remota de shell/SSH arbitrário como fallback; sem alteração de configuração WAN/SSID/OLT.

## Operação e limites P0 (configuráveis)
- RÁPIDO: 1 job ativo por ONT, ping inicial de 5 pacotes e DNS 2 tentativas; limite de 30–60s de trabalho ativo por dispositivo (exclui fila ACS), conforme homologação.
- COMPLETO: herdando **todos** limites do SD-001 (por ONT/PON/tenant/servidor) e deadline por direção. Nunca duplicar locks e testes simultâneos.
- Sem schedule para testes de carga; operação manual autorizada com indicação de impacto. Leitura passiva pode aproveitar o ciclo de coleta existente; evitar `refreshObject` indiscriminado.
- Falta de resposta do CPE/ACS: fila com timeout e backoff já existentes, sem laço de `Requested` nem reenvio automático de diagnóstico.
- Mudança de firmware invalida homologação cache de escrita e exige revalidação; recursos podem desaparecer.

## Observabilidade e rollback
- Métricas operacionais: qualidade por estado, timeout por modelo/firmware, latência de comunicação com ACS, número de refreshs CPE, fila de diagnósticos, saturação por PON/SD-001, rate limit.
- Feature flag OFF reverte **somente QoS**, sem desligar SD-001, inventário ou atendimento. Migrations aditivas ficam inertes durante rollback; seguir políticas existentes de DB.
- Flags sugeridas, com nomes adaptáveis: `diagnostics.quality.enabled` (OFF), `diagnostics.quality.active_tests.enabled` (OFF), `diagnostics.quality.full.enabled` (OFF). Ativar por tenant e modelos homologados.

## Abusos e testes negativos
- Usuário Viewer tenta iniciar; tenant A tenta ler run do B; IDOR com device/run; destino arbitrário injetado; URL com redirecionamento; HTML/JS em campos vendor; NBI retornando erros/senhas; async timeout; perda de comunicação após envio; inform atrasado de outro teste; firmware muda durante run; interrupção de Edge.
- Testar que valores sensíveis não aparecem em logs, respostas nem prompts LLM.
