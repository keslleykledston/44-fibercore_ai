# ADR-0022: Política de scores QoE (Optical Health / Home Experience)

Status: Proposed — **bloqueado por dados** | Data: 2026-10-29 | Owner: equipe | Origem: adendo v2.2, FC22-011/012/013, AC-008

## Contexto
O algoritmo v1 do adendo é paramétrico (subscores 0–100 ponderados, `coverage`, `insufficient_data`). Hoje só temos `rx_dbm` pontual por ONU (sem histórico, flaps, erros) e **nenhuma** telemetria Wi-Fi/WAN; limiares dependem de classe óptica/equipamento homologado e não existem para o nosso parque.

## Decisão
1. Nenhum score é publicado enquanto não houver: métricas esperadas definidas por perfil certificado, TTL de frescor aprovado, `min_coverage` aprovado e pesos aprovados **em ADR com aceite humano**. 2. Até lá a API responde `status: insufficient_data`, `score: null`, `coverage` real, lista das métricas indisponíveis — **nunca 0** e nunca valor imputado. 3. `algorithm_version` obrigatório e resultado reproduzível. 4. Home Experience exige antes: leitura de parâmetros Wi-Fi/WAN por allowlist de perfil certificado com redação (conflito C-09) e NBI fechado/autenticado.

## Consequências
FC22-011/012/013 ficam em S3 com dependência explícita; a UI mostra "dados insuficientes" em vez de gráfico vazio.
