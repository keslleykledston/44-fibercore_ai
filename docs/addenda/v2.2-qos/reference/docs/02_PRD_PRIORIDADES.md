# PRD — QoS-001 Diagnóstico de Qualidade da Conexão

## Objetivo e limites
Atender reclamações de instabilidade, lentidão ou Wi-Fi, apresentando evidências de onde investigar: ONT, PON/óptico, WAN/BNG, Core, Internet, Ethernet e Wi-Fi. **Não** declarar conformidade contratual/SLA automaticamente ou classificar causas como comprovadas sem evidências suficientes.

## Jornada N1/N2
1. Abrir detalhe da ONT no sidebar existente; visualizar a última medição e frescor por grupo.
2. Escolher `Diagnóstico rápido` (N1) ou `Diagnóstico completo` (N2 com permissão).
3. RÁPIDO: consultar métricas existentes/ACS (WAN, PPPoE, IP, PON, Ethernet, Wi-Fi, CPU, quando disponíveis); executar ping curto para CORE, depois DNS se suportados/autorizados. Nunca gerar tráfego saturante.
4. COMPLETO: incluir sequência do SD-001 para destino(s) selecionado(s) CORE e/ou INTERNET, e traceroute apenas se solicitado/compatível; avisar impacto de banda e pedir confirmação.
5. Exibir resultados, valores ausentes e razões; marcar recomendação de próximos testes e botão histórico.
6. Copilot recebe apenas resultados normalizados com fontes/frescor e oferece hipóteses, sem modificar configurações.

## Escopo obrigatório P0
- Descoberta de recursos reais por fabricante/modelo/firmware e evidências de escrita dos parâmetros de diagnósticos.
- Leituras: conexão WAN, PPPoE (se aplicável), IPv4/IPv6, Ethernet velocidade/erros, uptime/reboot, CPU/memória (opcional), óptica e Wi-Fi (se disponíveis ou adaptador OLT existente).
- Diagnósticos ativos: `IPPing` e `NSLookup` (somente onde existem); orquestração do ciclo `Requested→Complete/Error` com frescor e correlação.
- Inclusão de SD-001 no diagnóstico COMPLETO **por referência**, não por duplicação.
- Resultado por métrica: `value`, `unit`, `source`, `scope`, `collectedAt`, `freshness`, `status`, observação.
- Indicação `sem suporte`, `indisponível`, `expirado`, `inconclusivo`; nunca substituir ausência por zero.
- UX card/accordion dentro do drawer existente, sem nova rota no menu principal.
- Multi-tenant, RBAC, auditoria, controles de concorrência, flag OFF e testes automatizados.

## P1, se os blocos já existirem
- Traceroute sob demanda, status de clientes Wi-Fi, PHY, força de sinal e retries; delta de contadores (não interpretar acumulados isolados como taxa de erro).
- Regras de correlação simples explicáveis (ver `05_NORMALIZACAO_E_FRESCOR.md`).
- Capturas reais da UI, exemplos de troubleshooting e changelog na Central de Ajuda.

## Explicitamente fora do escopo
- Iperf ou speedtest novo, TR-471, auto-remediação, edição de Wi-Fi, reboot, alteração de WAN, Zabbix/NetBox novo, varredura massiva, inteligência preditiva e score "qualidade 95%".
- Execução periódica de testes pesados; a telemetria pode usar eventos/coletas já existentes.
- Provar rede interna a partir de teste originado na WAN da ONT.

## Regras de experiência
- Estado global pode ser `Atenção`, `Sem anomalias observadas` ou `Dados insuficientes`; nunca `Internet perfeita`.
- Diagnóstico rápido independente do motor TR-143 estar concluído; diagnóstico completo informa claramente indisponibilidade de banda sem travar a parte rápida.
- A comparação com o plano contratado só aparece se confirmada em fonte já integrada; nenhuma conclusão legal/SLA automática.
- Manter a interface sem números demais: 4 indicadores principais + "Ver detalhes por camada".

## Critérios objetivos
- RÁPIDO executável em ONT piloto com pelo menos telemetria WAN/Ethernet + ping; falhas parciais não quebram todo o fluxo.
- COMPLETO em ONT homologada referencia SD-001 válido; sem testes concorrentes em duplicidade.
- ONT bridge/management-only: não faz afirmação sobre banda/serviço; exibe parâmetros disponíveis e bloqueadores.
- Todos os resultados exibem fonte e idade, inclusive se obtidos via OLT.
- Não há testes de carga disparados sem autorização; ausência de suporte não gera falso alarme.
