# Edge Connector Go — Sprint 1 (interface; não implementado)

Implantar `cmd/fibercore-edge/main.go`, `internal/{auth,tunnel,heartbeat,queue,allowlist,connectors/{olt,genieacs,usp},audit,updater}`.

Contrato: outbound mTLS para Gateway; URL privada GenieACS NBI configurada localmente no site; SQLite persistente; envelope assinado anti-replay; TTL; erros tipados; operações só com adapter/homologação; SNMP e SSH read-only inicialmente. O Edge deve ser independente do ciclo de vida do GenieACS existente.

O diretório está propositalmente sem binário/serviço Go para não anunciar implementação inexistente.
