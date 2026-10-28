# Quickstart de desenvolvimento — ambiente demonstrativo

## Requisitos

Python 3.12+, Docker Engine + Compose V2, `make`, Git. Ambiente privado/teste; não ligar em OLT/GenieACS de produção.

## Validar documentos

```bash
python3 -m pip install PyYAML
make validate
```

## Subir bootstrap

```bash
# SOMENTE DEMO DEV. Altere a senha e proteja o .env real.
export FIBERCORE_DB_PASSWORD='troque_por_senha_de_desenvolvimento'
make compose-config
make up
curl http://127.0.0.1:8000/livez
curl http://127.0.0.1:8000/readyz
curl http://127.0.0.1:8000/modules
```

`/modules` demonstra catálogo com estado `unknown`/`disabled`; **não** é monitoramento efetivo. `DEMO_MODE` deverá ser desativado e acesso substituído por auth/RBAC real antes de staging externo. GenieACS real/Edge não instalados nesse Compose.

## Rodar testes do scaffold

```bash
python3 -m pip install -r starter/apps/api/requirements-dev.txt
cd starter/apps/api
PYTHONPATH=. pytest -q
```

## Segurança e operação

- Nunca comitar `.env`, segredos, contas de produção, dumps de CPE/ERP ou PSKs.
- Não publicar PostgreSQL, NATS ou GenieACS NBI externamente.
- Para produção, substituir NATS sem autenticação dev por NATS autenticado/TLS/ACL, pin de imagens por digest e observabilidade/hardening reais.
- Todo esquema, backlog e catálogo são pontos de partida revisáveis e exigem homologação técnica.

## Validação do adendo v2.1

```bash
python tests/validate_help.py
```

**Domínio final previsto:** `https://fibercore.devops.k3gsolutions.com.br` — ainda requer DNS, TLS e frontend real. O quickstart do scaffold é SOMENTE local e **não** deve ser publicado via Caddy até autenticação e RLS estarem implementadas.
