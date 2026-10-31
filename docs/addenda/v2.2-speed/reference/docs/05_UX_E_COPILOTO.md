# UX — Sidebar direito e copiloto

## Posicionamento exato
No drawer existente `EntityDetailDrawer` ou ONU 360°, logo abaixo de `Resumo da ONT` e `Estado Óptico`, adicionar **seção compacta** `Teste de banda`, acessível sem navegação extra. Reaproveitar a miniatura/ícone e o design system (iOS-like). Em tela estreita, usar drawer responsivo existente.

## Componentes mínimos
- Estado de compatibilidade: `TR-143 disponível` / `Parcial` / `Não suportado` / `Não homologado`.
- Segmented control `Core` | `Internet` (desabilitar destino sem teste ativo homologado).
- Botão `Iniciar teste` e texto discreto: `Este teste pode consumir banda durante a execução`.
- Durante a execução: `Aguardando ONT`, `Download`, `Upload`, `Finalizando` + indicador discreto e botão fechar drawer (job continua). **Não mostrar percentual fictício.**
- Resultado: dois KPIs (download/upload) e dois metadados no máximo (destino/interface), confiabilidade e horário; expandir `Detalhes técnicos` sob demanda.
- Histórico recente: últimos 5 (mais somente se componente já existir).
- Exibir aviso `Medição originada na ONT, não inclui Wi-Fi/LAN do cliente`.

## Microcopy
- Desconhecido: `Ainda não foi possível verificar suporte ao teste neste firmware.`
- Bridge: `Esta ONU opera em bridge e não dispõe de WAN IP de serviço para o teste direto.`
- Sem interface: `Selecione ou homologue a interface WAN de serviço antes de medir.`
- Parcial: `Download disponível; upload indisponível neste modelo.`
- Timeout: `O equipamento não retornou um resultado confirmado dentro do limite. A banda não foi determinada.`
- Resultado antigo: `Resultado anterior detectado: não utilizado nesta medição.`
- Teste de internet: `O destino externo também pode limitar a velocidade medida.`
- Plano nominal: `Referência do plano`, se validado; não usar selo SLA `Aprovado/Reprovado` sem política própria.

## Copiloto (somente leitura)
O copiloto pode resumir a medição **já persistida**, distinguindo PON, BNG e internet, e recomendar próximo teste (`medir com cabo`, `comparar no core`, `inspecionar potência óptica`), sem alegar causa única sem evidência. Não iniciar teste pesado automaticamente; se houver intenção, solicitar autorização por ação do operador e RBAC.

## Acessibilidade e consistência
- No máximo 2 KPIs destacados no card do teste.
- Sem gradientes exagerados ou animação chamativa; estados transmitidos por texto + ícone, nunca apenas cor.
- Drawer nunca toma toda a tela desktop; evitar scroll horizontal.
- Hora local em UI e UTC em dados. `—` para valor ausente, nunca `0` artificial.

## Screenshot e Central de Ajuda
Após implementar UI real, capturar telas dos estados: `disponível`, `em teste`, `resultado`, `incompatível`, `timeout` via browser do projeto. Publicar how-to na Central de Ajuda existente `/ajuda` e anexar imagem real; protótipo incluído no pacote não serve como captura de produto.

## Preview
Abrir `preview/index.html` para interagir com estados sintéticos; apenas referência visual, sem integração com ACS.
