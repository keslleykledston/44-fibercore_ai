# ADR-0036: ONT Configuration Manager — pré-visualização e pedido de mudança, sempre bloqueado (FC24-03)

Status: Accepted (pré-visualização e bloqueio; execução só com FC24-04 e homologação) | Data: 2026-10-31 | Origem: adendo v2.4; complementa o ADR-0034.

## Contexto
A leitura de configuração (ADR-0034) existe. O adendo exige que toda mudança tenha pré-visualização, validação, autorização, execução controlada, pós-verificação e auditoria, e proíbe qualquer escrita em ONT real sem homologação e autorização expressa. Não há executor, certificação de escrita nem janela de recuperação. Esta entrega cria o desenho do pedido e prova que ele não executa.

## Decisão
1. **Pré-visualização gravada, nunca execução.** `POST /v1/cpes/{id}/ont-config/changes/preview` valida, calcula o diff `de → para` por campo, o risco, as aprovações exigidas e **todos** os motivos pelos quais ainda não pode ir; grava o pedido (`cpe_config_changes`, RLS forçada) e audita `ont_config.change_previewed`. `POST …/changes/{id}/submit` **sempre devolve 409** (`executed: false`), grava `blocked` e audita `ont_config.change_blocked`. Não cria job, não chama o Edge, não toca no GenieACS. A tabela nem tem estado de execução.
2. **Lista fechada.** Cada capacidade de escrita aceita só os campos canônicos dela (`WRITE_FIELDS`), na instância que o aparelho informou (`instance_not_observed` caso contrário), com o mesmo validador da leitura. Coerência numérica extra: máscara contígua, endereço de host, faixa DHCP ordenada. Potência óptica nunca tem escrita.
3. **`If-Match`.** O corpo traz `if_match` = `form_revision` que o usuário viu; revisão diferente → 409 `stale_revision`. Na submissão a revisão é conferida de novo (se a configuração mudou depois, `stale_revision` entra nos bloqueios). `intent_hash` = sha256 canônico de {tenant, CPE, capacidade, instância, parâmetros, revisão-base, versão da política, versão do schema}. Validade 15 min (`410 preview_expired`; leitura mostra `expired`).
4. **Risco e aprovação (adendo).** R1: 1 aprovação, pode ser de quem pede; R2: 1 aprovação de outra pessoa; R3 (LAN/WAN): 2 aprovações de outras pessoas + plano de recuperação. Só informados aqui; a aprovação em si chega com o executor (FC24-04), reaproveitando `jobs:approve`.
5. **Bloqueios em ordem fixa:** `writes_not_enabled`, `capability_not_supported`, `capability_not_certified`, `stale_revision`, `stale_data`, `secret_channel_not_available`, `synthetic_source`, `executor_not_available`. O último é incondicional enquanto `EXECUTOR_AVAILABLE` for falso: mesmo com todo o resto liberado (provado por teste com monkeypatch) o pedido segue bloqueado.
6. **Segredos.** O valor de uma senha não entra no pedido: `wifi.password.write` aceita só `true` ("trocar"); qualquer texto → 422 sem eco do valor. O diff mostra "nova senha (valor não exibido)". A entrada real vem por `secret_ref` com TTL (FC24-05); até lá `secret_channel_not_available`.
7. **Permissões.** `ont_config:request` (R2; isp_admin, engineer, noc_n2; o NOC N1 só lê, como nas consultas à OLT) para Wi-Fi; `ont_config:request_high` (R3, MFA recente; mesmos papéis) para LAN/WAN. A rota exige a baixa; para capacidade R3 a rota confere a alta e o MFA no corpo da requisição (a capacidade vem do corpo). Só quem pediu pode submeter. Auditor, suporte e platform_support não pedem.
8. **Flag e rollback.** Sob a flag `ont_config` (desligada por padrão). Migração 0033 aditiva (`DROP TABLE cpe_config_changes`).

## Consequências
- A UI ainda não oferece botão de pedir mudança (próximo passo, junto com o executor); a API já descreve o contrato.
- Travas por dispositivo+capacidade, despacho de job, pós-verificação e rollback ficam para FC24-04/06; nada disso foi simulado como pronto.

## Alternativas descartadas
Aceitar o pedido e executar "só em laboratório" por flag (mistura pré-visualização com escrita; o caminho de bancada do ADR-0030 já cobre o laboratório autorizado); guardar a senha cifrada no pedido (o segredo não precisa existir na nuvem); fazer o 409 por exceção (desfaria a gravação do bloqueio e da auditoria).
