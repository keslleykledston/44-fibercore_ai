# Speed — download de 200 MB na ONT de bancada — 2026-10-31 — CONCLUÍDO, resultado CONFIÁVEL

Escopo: SOMENTE a ONT de bancada (Huawei EG8145V5 `V5R019C10S350`, serial de bancada `…7AA5`). Destino lógico `core-lab`, perfil `200mb`. Sem credencial, endereço ou dado de cliente. Registro `speed_test_download` já `observed` (aceite do responsável no chat: "aceito download"; ver `H-speed_test_download-1a-execucao-real-2026-10-31.md`).

## Resultado
- Desfecho gravado: **`completed`** (confiável), sem motivo de ressalva.
- **331,15 Mbps** de download em **4.961 ms**, **205.355.216 bytes** de teste (perfil de 200 MB). A duração passa do mínimo de 3 s, por isso o número é confiável como medição desta ONT até o nó de teste do LAB.
- Job `07fa958a-fc6f-4343-a518-cbd0a2a4e5e9` (`SUCCEEDED`, 10 s do aprovado ao concluído); execução `bd06b464-1c9b-47b2-9b77-35ae7513e12b`; hash da intenção `4af31595921192b519e9aac377d8d6b8cbe902b01ff1a8f156b27d024b84b73e`.
- Autorização de uso único `0684c95b…` (par exato `core-lab` + `200mb`), aprovada por conta diferente da que pediu. Janela: 2026-10-31 22:19 a 22:20 UTC. Flag `speed_diagnostics` desligada ao fim; bancada não ficou travada; 0 tarefas pendentes no ACS antes e depois.
- Origem que chegou ao nó (captura de SYNs): um único endereço, o da lista permitida; endereço não registrado aqui.

## Leitura do resultado
- A execução de 10 MB (parcial, 233 Mbps em 352 ms) subestimou a taxa: com arquivo curto a fase de partida da conexão domina. O valor de 200 MB (331 Mbps) é o que vale como medição.
- Este valor é o **caminho ONT → nó de teste do LAB** (um único sentido e uma repetição). Não é a velocidade contratada do cliente nem a capacidade da PON.

## O que ainda falta (homologação do download)
- **2 repetições adicionais** (total de 3) com o perfil de 200 MB, para ver a variação.
- **Comparação com uma medição cabeada de referência** (mesmo nó, mesma janela). Precisa de alguém na bancada.
- Upload: verificar antes (H1, só leitura) que `UploadDiagnostics` existe e é gravável neste firmware.
