# Imagens por digest

Toda imagem externa (Dockerfiles, `infra/compose/*.yaml`, `docker run` em `Makefile`/`scripts/`, serviços e `docker run` do CI) é referenciada como `repo:tag@sha256:<digest>`. O digest é o do **índice multi-arquitetura** (o mesmo que `docker pull` resolve em qualquer arquitetura). A tag fica só para leitura humana e para Renovate/Dependabot; quem manda é o digest.

- Fonte da verdade: `infra/images.lock` (uma linha por `<repo>:<tag>`).
- Verificação (offline, sem Docker): `python3 scripts/images.py check` — falha (rc=1) se algum `FROM`, `image:` ou ocorrência em script/Makefile/CI estiver sem digest, com digest diferente do lock, com variável (`$VAR`), fora do lock ou `PENDING`. Roda no CI (job `supply-chain`) e nos testes (`apps/api/tests/test_images_pinned.py`).
- Isentos: `FROM scratch`, `FROM <stage anterior>` e serviço de compose com `build:` (a tag é do build local, ex.: `fibercore-speed-node:local`).

## Atualizar digests (procedimento)

Digest só muda por decisão: é o que garante que o build de hoje é o de amanhã. Não rodar no meio de um deploy.

1. Branch própria. Com rede: `python3 scripts/images.py update` (dry-run: mostra `igual`/`MUDOU`/`NÃO RESOLVIDO` por imagem).
2. Revisar o que mudou (notas de versão da imagem; para `postgres`, só troca de menor dentro do major `17`).
3. `python3 scripts/images.py update --write` regrava o lock e todas as referências nos arquivos.
4. `python3 scripts/images.py check` e `docker compose --env-file <env> -f infra/compose/compose.yaml config --quiet`.
5. Reconstruir (`docker compose build`) e rodar a suíte: `scripts/test-env.sh` + pytest da API, `go test -race ./...` no Edge, e o scan do CI (Trivy HIGH/CRITICAL).
6. Commit pequeno (`chore(images): atualiza digests ...`) com o antes/depois do `update` no corpo. Em LAB: backup lógico antes do deploy (ver `DEPLOYMENT_PLAN.md`); troca de `postgres` ou `nats` recria o contêiner.
7. Mudar de **tag** (ex.: `nats:2.11-alpine` -> `2.12-alpine`): editar a linha do lock e as referências à mão (ou trocar a tag nos arquivos), depois `update --write`.
8. Adicionar uma imagem nova: acrescentar a linha ao lock com `PENDING`, rodar `update --write` (resolve e grava). Se não houver rede ou a imagem for privada, a linha FICA `PENDING` e o `check` falha até alguém resolver; nunca copiar digest de outra fonte sem conferir (`docker buildx imagetools inspect <ref>`: a linha `Digest:` do topo é a do índice e deve ser igual a `sha256sum` do `--raw`).

## Estado (2026-11-11)
- Resolvido e conferido por duas vias (`Digest:` do topo e SHA-256 do manifesto bruto): `postgres:17-alpine`, `nats:2.11-alpine`, `caddy:2.8-alpine`, `node:22-alpine`, `python:3.12-slim`, `golang:1.22-alpine`, `alpine:3.20`, `aquasec/trivy:0.58.1`, `zricethezav/gitleaks:v8.21.2`.
- Pendentes (digest não resolvido): nenhum.
- Atenção no primeiro deploy após esta mudança: na máquina da LAB, `nats` (`e4bf19f1...`), `caddy` e `alpine` já estão exatamente nesses digests; `postgres:17-alpine` e `node:22-alpine` locais tinham digests diferentes (`266d3c25...`, `16e22a55...`), ou seja, um rebuild/recreate passa a usar o 17.x/22.x atual da tag. Mesmo major; fazer backup antes (rotina normal de deploy). Nada foi puxado, recriado ou implantado na LAB por esta mudança.
- Fora de escopo: imagens construídas por cima (`fibercore-api`, `fibercore-web`, `fibercore-speed-node:local`) não têm digest do registro; assinatura/atestação de imagens segue pendente (`docs/security/SECURITY_AND_APPROVALS.md`).
