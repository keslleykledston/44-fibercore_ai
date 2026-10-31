# Diagnóstico de qualidade (QoS-001) — guia de homologação

Âmbito: a **leitura passiva** (PR A + B) não escreve em equipamento e não exige janela de bancada; mesmo assim, as flags `quality_*` ficam **desligadas** até esta planilha estar preenchida com dados reais e a pessoa responsável autorizar (ADR-0039). Os testes ativos (ping/DNS, PR C) dependem do caminho de Connection Request ou de uma emenda de "modo fila" e da bancada (ADR-0030); **nada disso está liberado**.

## 1. Pré-requisitos (só o responsável resolve)

| # | Pré-requisito | Estado |
|---|---|---|
| 1 | Nuvem com a migração 0037 e a UI do PR B implantadas | pendente (UI) |
| 2 | Estado do aparelho no cache do ACS **atual** (hoje o do aparelho de bancada está com ~40 h: o Connection Request do ACS responde 202 sem executar) | pendente |
| 3 | Perfil óptico homologado por classe de ONU (faixa de RX), para que a Óptica deixe de ser só "leitura sem faixa de referência" | pendente |
| 4 | Qual WAN é a de serviço do modelo (hoje toda leitura de WAN é `WAN_UNCLASSIFIED`) | pendente |
| 5 | Flag `quality_diagnostics` ligada só no provedor da homologação, com acompanhamento | pendente |

## 2. Planilha por modelo + firmware (preencher na execução real)

| Campo | Valor observado | Evidência (arquivo/ref.) | Verificado em |
|---|---|---|---|
| Fabricante / modelo / firmware | | | |
| ONU vinculada e confirmada à CPE (vínculo `confirmed`) | | | |
| `wan_link_status` / `wan_connection_status` presentes e atuais | | | |
| `uptime_seconds` presente e atual | | | |
| `wifi_radio_enabled` / `wifi_channel` presentes | | | |
| Nível óptico (RX) vindo da OLT, com horário da coleta | | | |
| Estado geral exibido × situação conhecida do aparelho (sem falso "sem anomalia") | | | |
| Idade do dado exibida × idade real do último Inform | | | |
| Aparelho sem leitura: a tela mostra "Sem leitura", nunca zero | | | |
| Perfil por perfil de papel (noc_n1 lê/pede; sem permissão não vê o botão) | | | |
| Captura real da aba Qualidade no LAB (identificadores mascarados) | | | |

## 3. Critério de saída

Todas as linhas acima preenchidas com evidência, flag ligada só no provedor autorizado, revisão do Codex sem CRITICAL/HIGH e **autorização escrita** da pessoa responsável. Sem isso, o estado continua: **implementado, desligado, não homologado**.
