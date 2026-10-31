# UX mínima — dentro do ONU 360 / sidebar recolhível existente

## Princípio
Adicionar seção **Qualidade do serviço** na área de diagnósticos já criada para o SD-001. Não duplicar `EntityDetailDrawer`, não criar menu de QoS geral, não redesenhar ONT.

```text
[ONT • Huawei X • online]             [fechar]
[status PON] [Firmware] [WAN service]
────────────────────────────────────────────
Qualidade do serviço      Última coleta 12:18
[ RÁPIDO ]   [ COMPLETO ]

Conexão IP         4 ms     0% perda
Fibra              -23,5 dBm   via OLT
Wi-Fi              Dados parciais
Porta LAN 1        100 Mbps   ATENÇÃO
[ Executar diagnóstico ]

[ Ver detalhes por camada ▾ ]
[ Hipóteses ▾ ]
[ Histórico  ▾ ]
```

## Comportamentos
- **RÁPIDO (padrão):** ping/DNS (se homologados), leitura de WAN, óptico, LAN, Wi-Fi; exibidos em 4 linhas ou cards compactos com expansão. Sem banda saturante.
- **COMPLETO:** seletor de destinos `Core`, `Internet` (um ou ambos conforme RBAC), aviso sobre tráfego gerado; utilizar o mesmo módulo de SD-001; traceroute opcional oculto em `Avançado`, se homologado.
- Durante: progresso por estágio: `Na fila`, `Consultando WAN`, `Ping`, `DNS`, `Banda Core`, `Banda Internet`, `Finalizando` (conforme plano real). Sem percentuais inventados.
- Ao falhar parcialmente: preservar indicadores válidos e explicar linha `Não suportado`, `Sem resposta`, `Dados antigos`.
- Card de diagnóstico **não toma todo sidebar**; `Ver detalhes` recolhível. Sem medalhas verdes por dados faltantes.
- Histórico curto (últimos 5 ou padrão existente) e ação `Ver mais` apenas se já houver padrão para página de histórico.
- Badges discretos `Atenção`, `Sem anomalias observadas`, `Inconclusivo`; não usar score numérico QoE.
- Browser nunca recebe senha do CPE, conexão ACS, URL com token, MACs e SSIDs de terceiros, endereços de destino não necessários.
- Página `preview/quality-addon.html` é apenas exemplo estático, **não é tela implementada**.

## UX de capacidade
- `PON não disponível pelo TR-069; dado da OLT`: informar claramente.
- `Sem medição direta em bridge`: bloquear afirmação de banda, mas mostrar sinais/estado coletados.
- `Wi-Fi ausente`: usar `Não se aplica`, não 0 ou problema.
- `Firmware não homologado`: `Diagnóstico ativo indisponível para este modelo`, e continuar telemetria segura se existente.
- `Info ausente`: indicar `dados insuficientes`; propor procedimento presencial/sonda/roteador quando exigido.

## Copilot (somente interpretação)
Input: `QualityRun` normalizado e saneado, com fonte, horário, status por métrica e hipóteses calculadas pelo motor determinístico. Output: resumo de até 4 linhas, 1–3 causas **possíveis** em linguagem probabilística e próximos testes; citar IDs das evidências. O copiloto NÃO altera `confidence`, não emite diagnóstico jurídico/SLA e não dispara comandos/alterações/reboots/reprovisionamento. Qualquer manobra futura segue fluxo de aprovação separado já existente.

## Manual de ajuda e capturas
Após PR de UI e homologação de laboratório:
1. Abrir frontend local real no ambiente de desenvolvimento, não usar apenas o preview.
2. Capturar estados: disponível, em teste, dados parciais, bridge, falha/timeout; legendas "ambiente de testes" quando for mock.
3. Publicar how-to na Central de Ajuda existente `/ajuda`, incluir origem das medidas e limites do teste da ONT.
4. Atualizar changelog e a matriz de suporte por fabricante/firmware.
