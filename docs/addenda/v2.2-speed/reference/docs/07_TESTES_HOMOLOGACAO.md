# Testes e matriz de homologação

## Testes automatizados
| ID | Cenário | Aceite |
|---|---|---|
| T01 | ONT TR-143 Device:2 completa | Detecção suportada, interface validada |
| T02 | ONT IGD:1 completa | Root correto, sem prefixos misturados |
| T03 | Bridge apenas gestão | Bloqueio com causa clara; nenhum tráfego gerado |
| T04 | Só DownloadDiagnostics | Upload `—`, estado `partial`, não 0 Mbps |
| T05 | HTTP 202 do GenieACS | Aguardar; não concluir nem reemitir Requested |
| T06 | Evento `8 DIAGNOSTICS COMPLETE` | Buscar resultado e validar frescor |
| T07 | Completed anterior | Rejeitar stale e mostrar inconclusivo |
| T08 | Erro TR-143 `Error_*` | Registrar erro e preservar outras direções |
| T09 | BOM/EOM inválidos | Resultado inconclusivo, evita divisão por zero |
| T10 | TestBytesReceived 100000000/10s | Download 80.00 Mbps |
| T11 | Upload TestFileLength 50000000/10s | Upload 40.00 Mbps se upload concluído |
| T12 | Sobreposição por PON | `409` ou fila protegida, nunca sobrecarga |
| T13 | Usuário viewer | 403 ao iniciar |
| T14 | Device outro tenant | 403/404, sem vazamento |
| T15 | URL arbitrária em payload | Rejeitar; somente catálogo aprovado |
| T16 | Edge/ACS indisponível | UI isolada e fallback seguro |
| T17 | Test node sem PUT | Falha upload clara, sem falsa medição |
| T18 | Firmware muda | Revalidar capability/homologação |
| T19 | Teste curto/servidor saturado | Qualidade parcial/inconclusiva |
| T20 | Feature flag OFF | Nenhuma escrita; demais funcionalidades íntegras |

## Homologação real — piloto
- **Registro por combinação** `vendor / model / firmware / TR root / método / WAN ref`.
- Identificar ONT roteada com IP de serviço; confirmar fora do perfil de gestão.
- Testar CORE e INTERNET no mesmo equipamento, download e upload, controlando tráfego concorrente.
- Repetir 3 vezes em horário de baixa carga e confrontar com medição cabeada independente no mesmo perfil (ambas medem caminhos diferentes; discrepância pede investigação, não equivalência automática).
- Coletar tempos, bytes, HTTP status, eventos/Inform, falhas, CPU CPE (se disponível), PON/OLT, link do Test Node, referência de plano e congestionamento.
- Testar caso negativo: bridge puro, CPE não responsivo, servidor com falha, equipamento sem writable, contador stale.
- Só habilitar `SUPPORTED` após prova real e registrar observações de qualidade por firmware.

## Critérios de aceite finais
1. O fluxo tem **prova ponta a ponta** em ambiente de laboratório com ONT real, sem degradar serviços do FiberCore.
2. O QA confirma GET e **PUT** do Test Node, sem upload salvo em disco.
3. Resultados reais permanecem após fechar/reabrir drawer e aparecem no histórico.
4. Capturas reais e how-to em `/ajuda` atualizados.
5. Reviewer Codex: **PASS**, ou WARN aceito formalmente em aspectos não críticos; BLOCK impede merge.

## Evidências a entregar no PR
`tests/*`, logs anonimizados de tasks (200 e 202), evidência de `8 DIAGNOSTICS COMPLETE` quando presente, print de capacidade por firmware, screenshot do drawer, diff de migrações, plano de rollback e changelog v2.2 adendo.
