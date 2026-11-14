# Encerrar uma organização (ADR-0050) — roteiro do dono

**Irreversível.** A tela do operador só PEDE; quem exporta e apaga é o dono, no host. Comandos pelo serviço `migrate` (tem a conexão admin):

```
DC="docker compose -p fibercore-prod --env-file .env.prod -f infra/compose/compose.yaml"
```

## 0. Antes de tudo
- Backup lógico do banco (`COMPOSE_PROJECT=fibercore-prod ENV_FILE=.env.prod scripts/backup.sh`) e conferência do arquivo.
- A organização **não** pode ser de demonstração.

## 1. O operador pede (tela da organização, ou API)
1. Suspender a organização (motivo obrigatório). Ela precisa estar **suspensa**.
2. "Pedir encerramento" (`POST /v1/platform/organizations/{id}/closure`, motivo). Abre a **carência de 7 dias** (`earliest_close_at`). Reativar a organização cancela o pedido; "cancelar pedido" também.

## 2. O dono exporta (depois do pedido)
```
$DC run --rm --no-deps -T -v /caminho/seguro:/export migrate python -m app.cli org-export <tenant_id> --out /export/<nome>.tar.gz
```
Guarde o `sha256` impresso. O arquivo (0600, nunca sobrescreve) tem um `.jsonl` por tabela e um `manifest.json`; **contém dado pessoal de cliente final** e **nenhum** hash de senha, token ou blob selado. Entregue a quem de direito e guarde como um backup.

## 3. O dono confere e apaga (depois da carência)
Primeiro o ensaio (faz todas as conferências e não apaga):
```
$DC run --rm --no-deps -T -v /caminho/seguro:/export migrate python -m app.cli org-close <tenant_id> --confirm-name "NOME EXATO" --export-file /export/<nome>.tar.gz --dry-run
```
Depois, sem `--dry-run`. Recusa até que: exista, não seja demo, esteja suspensa, haja pedido aberto, a carência tenha acabado, o nome seja exato, o export seja posterior ao pedido, o arquivo tenha o mesmo sha256 registrado e os dados atuais tenham as mesmas contagens do export (mudou algo: exporte de novo). Tudo numa transação: se falhar, nada é apagado.

## 4. Depois
- Sobra um registro mínimo permanente (nome, motivo, quem/quando, hash do export, linhas apagadas por tabela), visível em `GET /v1/platform/closures`.
- Contas que só existiam nessa organização ficam **desativadas** (não apagadas). Contas que pertencem a outra organização não são tocadas.
- Mensagens já no JetStream com o tenant expiram pela retenção do fluxo.
- **Não há restauração a partir do export** (não existe importador). Reverter = restaurar o backup do passo 0.
