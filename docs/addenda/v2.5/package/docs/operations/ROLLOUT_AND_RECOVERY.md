# Operação, implantação e recuperação

**Flags padrão:** writes desativados por tenant e por driver/OLT; gates independentes para criação de profiles, autorização ONU, migração e bulk.

**Rollout:** iniciar com fixtures → read-only de uma OLT autorizada → diff/simulação → LAB canário de profile não utilizado → validar sem afetar ONUs → autorização piloto → somente então produção mediante change aprovada. Multi-OLT é fase posterior com canário e concorrência limitada.

**Observabilidade:** medir idade de descoberta, idade do snapshot, import failures, quality unknown, reuse vs clone, diffs conflitantes, jobs aguardando aprovação, duração do readback, partial/unknown e número de ONUs potencialmente afetadas. Alertar `PARTIAL/UNKNOWN`, nunca mostrar sucessos falsos.

**Falha durante provisionamento:** marcar estado exato, congelar replay de ação não idempotente, coletar evidência read-only atual, reconciliar desired/observed e criar novo plano de compensação com revisão/aprovação. Não deletar profile com referências; se ONU parcialmente registrada, confirmar IDs e service-port antes de qualquer reenvio.

**Drift por CLI externo:** detectar e sinalizar divergência, invalidar plano, nunca corrigir automaticamente. Se profile foi editado fora do FiberCore, nova importação e novo diff.

**Escopo:** contingência de conexão Edge não permite bypass público SSH à OLT; backend não abre conexão direta à rede privada do ISP.
