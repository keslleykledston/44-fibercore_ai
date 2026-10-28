# Release Center — atualizações de serviços, agentes e firmware

## Quatro classes com políticas diferentes

1. **Backend/Frontend/Workers:** release versionada Git -> registry assinatura/SBOM -> staging -> canary -> aprovação platform admin -> deploy; em K3s readiness + rolling updates com >=2 réplicas, em Compose janela controlada e indisponibilidade potencial.
2. **FiberCore Edge/Adapters:** mecanismo pull seguro, manifesto assinado, SHA-256, versão mínima do gateway, compatibilidade contrato, canário por site, troca atômica com watchdog próprio e health rollback possível.
3. **Drivers/Templates:** registros versionados com capabilities por firmware, pipeline `identified -> observed -> certified`, homologação/QA Codex + NOC antes de release; não executar templates não certificados.
4. **Firmware OLT/ONU/ONT/CPE:** job de risco R3, arquivos autenticados e origem licenciada, validação vendor/model/firmware, lote canário, janela e aprovação dupla, plano de recuperação por modelo (rollback pode ser impossível), monitoramento pós-instalação e fila suspensa se blast radius passar limiar.

## Contrato `release` e changelog

`release_id`, `component_id`, `semver`, `git_sha`, `artifact_sha256`, `sbom_ref`, `notes_pt_br`, `breaking_changes`, `min_platform_api_version`, `compatible_firmware_ranges`, `canary_targets`, `approved_by`, `approved_at`, `rollout_state`, `monitoring_window`, `rollback_plan_ref`.

Estados: `draft`, `tested`, `pending_review`, `approved`, `canary`, `paused`, `promoted`, `rolled_back`, `failed`.

## UI

Página mostra versões instaladas por módulo/tenant, release disponível, changelog, criticidade, incompatibilidades, aprovações e impacto. A plataforma pode notificar atualizações; **não deve atualizar silenciosamente firmware de rede nem substituir instalação GenieACS do ISP**. Requisitos de consentimento de tenant são separados de privilégio de infraestrutura Cloud da K3G.

## Política de falhas

Se módulo opcional degradar em canário: pausar rollout, preservar módulos saudáveis, rollback por componente e alerta para equipe; persistência/migrações reversíveis por expand/contract. Firmware sem rollback suportado permanece travado até revisão manual.
