# Integrações: tokens de API e webhooks (ADR-0051)

Para o **administrador do provedor**. Os dois exigem segundo fator recente; só o papel Administrador do provedor os gerencia.

## Token de API (só leitura)
1. Crie em `POST /v1/api-tokens` (`{"name": "BI do NOC", "permissions": ["inventory:read", "incidents:read"], "days": 90}`). O token (`fcat_…`) **aparece uma vez**: guarde-o num cofre.
2. Use: `Authorization: Bearer fcat_…` em qualquer rota de **leitura** coberta pelas permissões dadas (`GET /v1/olts`, `/v1/onus`, `/v1/incidents`, `/v1/fleet/olts`…). Qualquer outra rota responde 403.
3. Limite de 120 requisições por minuto (rajada 60) por token; 429 traz `Retry-After`.
4. Revogue em `DELETE /v1/api-tokens/{id}`; vale na hora. Organização suspensa fecha todos os tokens dela (voltam ao reativar).
5. Permissões possíveis: `inventory:read`, `incidents:read`, `fleet:read`, `discovery:read`, `diagnostics:quality_read`.

## Webhook de saída
1. Pré-requisito do operador do servidor: `FIBERCORE_WEBHOOK_ENCRYPTION_KEY` (chave Fernet) e o serviço `webhooks` no ar, com saída HTTPS. Sem a chave a API responde `503 webhooks_unavailable`.
2. Registre em `POST /v1/webhooks` (`{"name": "NOC", "url": "https://hooks.exemplo.com.br/fibercore", "events": ["incident.opened", "incident.resolved"]}`). A URL tem de ser **https** com **nome** público (nunca IP, `localhost` ou nome interno). O **segredo** (`whsec_…`) aparece uma vez.
3. Teste: `POST /v1/webhooks/{id}/test`; o resultado está em `GET /v1/webhooks/{id}/deliveries`.
4. **Confira a assinatura** de cada chamada (cabeçalho `X-FiberCore-Signature: t=<unix>,v1=<hex>`): `hex = HMAC-SHA256(segredo, "<t>.<corpo bruto>")`; recuse se `t` tiver mais de 5 minutos. Exemplo em Python:

```python
import hmac, hashlib, time
def valido(segredo: str, cabecalho: str, corpo: bytes, tolerancia=300) -> bool:
    p = dict(x.split("=", 1) for x in cabecalho.split(","))
    if abs(time.time() - int(p["t"])) > tolerancia:
        return False
    esperado = hmac.new(segredo.encode(), p["t"].encode() + b"." + corpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, p["v1"])
```
5. Responda **2xx** rápido (10 s no máximo). Sem 2xx a plataforma tenta de novo com recuo (até 8 vezes em 24 h). **10 falhas seguidas desligam o endpoint**; religue com `PATCH /v1/webhooks/{id}` `{"active": true}`.
6. O corpo traz só ids e contagens (`incident_id`, `kind`, `pon_path`, `onus_down`…): nunca nome nem dado de cliente.
7. Troque o segredo com `POST /v1/webhooks/{id}/rotate-secret` (o antigo para de valer na hora).
