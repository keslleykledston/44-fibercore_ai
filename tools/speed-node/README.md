# speed-node — nó de teste de banda (Speed Diagnostics, ADR-0038)

Servidor HTTP mínimo que fala exatamente o contrato dos modelos de URL do Edge:

| Método e caminho | Resposta |
|---|---|
| `GET /health` | 200, corpo exato `ok` (a sonda de saúde do Edge) |
| `GET /dl/<perfil>` | 200, exatamente `<perfil>` bytes incompressíveis, `Content-Length` fixo |
| `PUT /ul/<perfil>` | 200, corpo descartado (nunca gravado), no máximo `<perfil>` bytes (senão 413) |

`<perfil>` = `10mb` (10 000 000 B), `50mb`, `200mb`. Qualquer outro caminho dá 404; outro método, 405.

## Garantias (cobertas por testes em `main_test.go`)
- **Nunca redireciona** (sem `http.ServeMux`, que emitiria 301/308 em caminhos não limpos): um CPE que seguisse um 3xx poderia ser desviado.
- Não comprime, não faz cache, não guarda nada do que recebe, **não registra endereço de cliente**.
- Não sobe sem endereço de escuta explícito (curinga recusado) nem sem lista de origens permitidas (`/0` e prefixos largos recusados).
- Origem fora da lista: 403. Mais de N transferências simultâneas (padrão 2, máx. 8): 429. `/health` não conta como transferência.

## Executar (no host do provedor, como usuário sem privilégio)
```bash
CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o speed-node .
SPEED_NODE_LISTEN=<ip-da-interface>:<porta> \
SPEED_NODE_ALLOW=<rede-de-serviço-da-ONT>/<n>,<ip-do-host-do-Edge>/32 \
./speed-node
```
- `SPEED_NODE_ALLOW` deve conter a rede de onde sai o tráfego da WAN de serviço da ONT (o endereço que o nó **enxerga**, depois de NAT/BNG) **e** o host do Edge (sonda `/health`).
- O firewall do host precisa liberar a porta só para essas origens. O nó não substitui ACL.
- O endereço e a porta vão **somente** na configuração local do Edge (`speed.endpoints`) — nunca na nuvem, no repositório ou na tela.
- Parar o nó encerra o teste: o Edge passa a ver `down` na próxima sonda e a nuvem deixa de oferecer o teste.

Não é um servidor de benchmark certificado: a capacidade do enlace e da CPU do host é fato de homologação (planilha em `docs/operations/SPEED_HOMOLOGACAO.md`).
