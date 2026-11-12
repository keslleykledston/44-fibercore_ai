# Edge: cadastro de ACS por organização e `acs-status` (ADR-0046 D2)

A nuvem passa a ter o **cadastro** do ACS de cada Edge (nome, tipo, Edge, ligado/desligado) e a mostrar se ele responde. **A URL e o usuário/senha do NBI continuam só no `config.json` do Edge** (ADR-0041 D3); a nuvem nunca os recebe, guarda ou devolve. Contrato exato: `docs/wiki/adr/ADR-0046-organizacoes-isoladas-acs-por-organizacao-e-centro-de-olt.md` (D2).

**Tudo é opt-in.** Sem `nbi_cloud_id` o Edge se comporta exatamente como antes e não envia nada novo. Sem a flag `acs_registry` ligada para o provedor, a nuvem responde 404 a tudo isso e o Edge só registra uma linha de aviso (uma vez).

## Como ligar (nessa ordem)
1. **Edge**: atualize o binário (entende `nbi_cloud_id`; um Edge antigo ignora a nuvem nova sem erro).
2. **Nuvem**: o dono liga a flag do provedor: `feature-set <provedor> acs_registry on`.
3. **Tela** `Rede > ACS` (permissão `acs:manage`, papel Administrador): cadastre o ACS (nome, tipo `genieacs`, o Edge). A tela mostra o **identificador** do ACS (UUID).
4. **Edge**: coloque o identificador no `config.json`, ao lado do `nbi_url` que já existe, e reinicie o serviço:
   ```json
   "nbi_url": "http://127.0.0.1:7557",
   "nbi_secret_file": "/etc/fibercore-edge/nbi.secret",
   "nbi_cloud_id": "5f0c1d52-1b5e-4c36-9a3e-0f6a3f0d8c11"
   ```
   Regras: UUID **em minúsculas** (o mesmo formato do `cloud_id` da OLT); exige `nbi_url`; qualquer outra coisa faz o Edge recusar o arquivo na partida. É só um identificador: não é segredo.

## O que o Edge envia
A cada rodada do coletor de NBI **que já existe** (a mesma leitura `GET /devices`; nenhum tráfego novo ao ACS), um item `acs_status` entra na fila durável, depois do inventário, e segue para `POST /v1/edge/acs-status`:
```json
{"acs_id": "<nbi_cloud_id>", "kind": "genieacs", "ok": true,  "device_count": 1234, "error_code": null}
{"acs_id": "<nbi_cloud_id>", "kind": "genieacs", "ok": false, "device_count": null, "error_code": "timeout"}
```
- `ok:true` leva o número de dispositivos que o ACS devolveu (inclui os que o inventário deixa de fora, como `DISCOVERYSERVICE`; zero é uma resposta válida) e nenhum código; `ok:false` leva **só** um código e nenhuma contagem. Nunca vai URL, host, usuário, senha, texto de erro ou id de aparelho.
- `error_code` é de lista fechada: `unreachable` (rede, DNS, conexão recusada ou cortada), `timeout`, `unauthorized` (401/403 do ACS: confira `nbi_secret_file`), `unexpected_status` (outro status HTTP), `bad_response` (JSON inválido), `too_large` (resposta acima de 16 MiB), `unknown`.
- A rodada cancelada (parada do serviço) não é falha do ACS e não gera item.
- O item é do mesmo fluxo (`acs_status:<id>`): uma rodada completa nova substitui a anterior que ainda esteja na fila.

## Respostas da nuvem e o que o Edge faz
| Resposta | Significado | Edge |
|---|---|---|
| 204 | gravado | confirma o item |
| **404** | nuvem antiga (sem a rota), flag `acs_registry` desligada, `nbi_cloud_id` que não é deste Edge, de outra organização ou de outro tipo (o 404 é o **mesmo** em todos os casos, de propósito) | **descarta** o item, não conta como falha, nunca vai para a fila de mortos, e escreve **uma única** linha de aviso por processo (`cloud does not know this ACS report`) |
| 429 | orçamento de ingestão do agente esgotado | espera o `Retry-After`, o item fica (não é falha) |
| 5xx, 408, rede | transitório | mantém o item e tenta de novo, na ordem |
| 422 | formato recusado (bug de versão) | vai para a fila de mortos e é logado como erro |

## Operação
- A tela mostra: ativo/inativo, "visto há…", número de dispositivos e o último erro em português. "Sem leitura" = o Edge ainda não reportou (confira o `nbi_cloud_id` e a flag); "Desatualizado" = nenhum relato há mais de 20 minutos (Edge parado ou sem rede).
- **No máximo um ACS ativo por Edge** (o Edge tem uma única `nbi_url`). Para trocar de ACS: desative o atual, ative o outro, ponha o identificador novo em `nbi_cloud_id` e reinicie. Enquanto o `nbi_cloud_id` do Edge apontar para o antigo, ele continua sendo o que recebe os relatos.
- Os CPEs lidos passam a levar `acs_id` (o ACS **ativo** do Edge no momento da leitura; nulo se não houver). Trocar o ACS ativo **não** reescreve CPEs antigos, e nada é preenchido para trás.
- Rollback: desligue a flag `acs_registry` (telas e rotas somem; o Edge só avisa uma vez) ou remova `nbi_cloud_id` do `config.json`. Nada mais depende disso.
