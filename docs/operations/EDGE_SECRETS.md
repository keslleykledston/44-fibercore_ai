# Edge: credenciais de OLT entregues pela tela (ADR-0045)

Lado do Edge da entrada segura de login, senha e community SNMP. O navegador cifra o segredo com a chave pública deste Edge; a nuvem só guarda texto cifrado; só este host o abre. Contrato exato (criptografia, AAD, assinatura, estados, códigos): `docs/wiki/adr/ADR-0045-credenciais-de-olt-pela-tela-cifradas-ate-o-edge.md`. Vetores de teste: `docs/addenda/olt-secrets/vectors.json`.

**Tudo é opt-in.** Sem a seção `olt_secrets` no `config.json` o Edge não publica chave, não pergunta por entregas e recusa qualquer `credentials_file` (erro de configuração). Um Edge com a configuração antiga fica idêntico.

> **ADR-0046 (emenda):** a nuvem também pode entregar a **conexão** de uma OLT (`kind:"olt_connection"`), mas só dentro da seção local `managed_olts` e só depois de `fibercore-edge managed-trust`. Passo a passo, política e reversão: `docs/operations/EDGE_MANAGED_OLTS.md`. Sem essa seção o texto abaixo vale como está.

## O que o Edge nunca deixa a nuvem mudar
Endereço, `host_key_sha256`, `allowlist`, a lista de OLTs e o perfil continuam só no `config.json` local (a exceção, opt-in e sob confiança local, é a seção `managed_olts` acima). A entrega só preenche as credenciais de uma OLT **já configurada** e que o administrador do Edge habilitou com `credentials_file`. A entrega **não** troca a senha na OLT: só atualiza a cópia que o Edge usa.

## Habilitar (por OLT)

1. **Diretórios (usuário do serviço do Edge; modo 0700).** O Edge não cria o diretório das credenciais (quem administra o host decide); o da chave ele cria se faltar.
   ```bash
   sudo install -d -m 0700 -o <usuario-do-edge> -g <usuario-do-edge> /var/lib/fibercore-edge/olt-credentials
   sudo install -d -m 0700 -o <usuario-do-edge> -g <usuario-do-edge> /var/lib/fibercore-edge/seal
   ```
   Caminhos **absolutos**. Arquivo e diretório precisam ser do usuário que roda o Edge, sem nenhum bit para grupo/outros; do contrário o Edge recusa (a sessão da OLT falha fechada).
2. **`config.json`** (campos novos; o resto não muda). `job_public_key` é obrigatório: é com ela que o Edge verifica a assinatura de cada entrega.
   ```json
   "job_public_key": "<a mesma já fixada para os jobs>",
   "olt_secrets": {
     "seal_key_file": "/var/lib/fibercore-edge/seal/seal-key.json",
     "applied_file": "/var/lib/fibercore-edge/olt-secrets-applied.json",
     "poll_seconds": 30
   },
   "olts": [
     { "name": "OLT-CENTRO-01", "...": "(campos de sempre)",
       "credentials_file": "/var/lib/fibercore-edge/olt-credentials/OLT-CENTRO-01.json" }
   ]
   ```
   - `applied_file` e `poll_seconds` são opcionais (padrões: `olt-secrets-applied.json` ao lado da fila; 30 s; aceito 15 a 300).
   - **A presença de `credentials_file` é a permissão.** `name` precisa ser igual ao nome da OLT no Cloud (entra na AAD).
   - Com `credentials_file`, `username` e `secret_file` (CLI) ou `snmp_community_file` (SNMP, `last_down`) deixam de ser obrigatórios: o conteúdo só é exigido quando a sessão começa. Mantê-los dá um fallback campo a campo (ver Precedência).
   - Cada OLT tem o **seu** arquivo; dois `credentials_file` iguais, ou igual a outro arquivo de segredo, são recusados.
   - Tipos aceitos por entrada: `ssh_login` em OLT CLI; `snmp_community` em OLT `transport: "snmp"` ou em OLT CLI com `last_down`. Um tipo que a entrada nunca usaria é recusado (`target_not_configured`), não "aplicado".
3. **Reiniciar o Edge.** No primeiro start ele gera a chave (`seal_key_file`, 0600, par ECDH P-256; a privada nunca sai do host nem aparece em log) e a publica (`POST /v1/edge/seal-key`). O log avisa `a new seal key was generated`.
4. **Confirmar a impressão digital** (passo humano, obrigatório; sem isso a nuvem recusa entregas):
   ```bash
   fibercore-edge seal-fingerprint -config /etc/fibercore-edge/config.json
   ```
   Imprime `fingerprint` (8 grupos de 4 hex), `key_id` e `public_key`. Compare **grupo a grupo** com o que a tela de Frota mostra para este Edge e só então confirme na tela (permissão `fleet:secrets`, auditado). O comando não gera a chave (se ela não existe, diz para iniciar o Edge uma vez) e não imprime nenhum segredo.
5. Ligar a flag `fleet_secrets` do provedor na nuvem por último.

## Como o Edge aplica uma entrega (ordem do ADR)
1. Verifica a assinatura Ed25519 (com `job_public_key`), o `key_id`, a AAD reconstruída com **este** tenant/Edge e a OLT da entrega, e a validade; 2. abre o blob e valida o JSON (limites, sem CR/LF/NUL); 3. se o `delivery_id` já consta como aplicado, **não regrava** e informa `applied`; 4. grava o `credentials_file` (temporário 0600 no mesmo diretório, fsync, rename, fsync do diretório, sob trava, lendo e mesclando: `ssh_login` troca usuário+senha juntos, `snmp_community` só a community); 5. registra o `delivery_id` no armazém de aplicados (atômico); 6. envia o resultado com o `lease_token` da tentativa.

Falhas informadas (códigos do ADR): `bad_key_id`, `expired`, `aad_mismatch`, `bad_signature`, `decrypt_failed`, `invalid_payload`, `stale`, `target_not_configured`, `write_failed`, `state_unreadable`. Nenhum valor secreto vai em log, erro, resultado ou arquivo temporário legível por outro usuário.

- `429` e `5xx` da nuvem são transitórios: nada é contado contra a entrega, o Edge tenta no próximo ciclo e respeita `Retry-After` (a janela de espera destas rotas é própria; não segura o envio de coletas, e a janela de ingestão existente é respeitada).
- `409 stale_lease` no resultado: o Edge pergunta `next` de novo; a reentrega cai no passo 3 e informa `applied`.
- **Efeito na coleta.** O Edge só lê o arquivo no começo da **próxima** sessão da OLT. Ele não abre sessão, não mexe no guard de ritmo nem no cooldown: se a coleta anterior falhou por senha errada, a OLT segue em cooldown (padrão 15 min no CLI) e usa a credencial nova quando o guard liberar.

## Precedência na leitura (por sessão: SSH, SNMP e `last_down`)
- Campo presente no `credentials_file` vale; campo ausente cai para a configuração estática (`username`, `secret_file`, `snmp_community_file`, e o `snmp_community_file` do `last_down`).
- Arquivo **ausente** = só a configuração estática.
- Arquivo ilegível, permissão frouxa (grupo/outros), diretório aberto, de outro usuário, link simbólico, JSON inválido, versão desconhecida ou valor fora dos limites = **erro da sessão, sem cair para outra fonte**. A OLT fica sem coleta até alguém consertar (log `olt collection failed` com o motivo, sem valores).

## Rotação da chave de selagem
1. (Opcional) esperar não haver entrega em voo na tela.
2. Parar o Edge, apagar `seal_key_file` (ou movê-lo para fora do diretório), iniciar o Edge: ele gera uma chave nova e a publica; a nuvem a marca **pendente** e cancela as entregas `PENDING`/`DISPATCHED` da antiga.
3. Repetir o passo 4 de "Habilitar" (impressão digital e confirmação).
Entregas seladas para a chave antiga falham com `bad_key_id`. O Edge usa **uma** chave por vez. Um arquivo de chave existente mas ilegível/corrompido **não** é substituído sozinho: o Edge se recusa a iniciar (para não orfanar entregas em silêncio); consertar ou rotacionar de propósito como acima.

## Armazém de aplicados (`applied_file`)
Guarda os `delivery_id` aplicados por pelo menos 24 h (no máximo 1000) e, por OLT + tipo, o `expires_at` da última aplicada (uma entrega com `expires_at` **anterior** é `stale`: impede reaplicar um blob antigo). Não tem segredo, mas é estado de **integridade**: o Edge só o usa se o diretório for do usuário do Edge e **sem escrita para grupo/outros**, e o arquivo for do usuário do Edge, 0600, não link simbólico (senão `state_unreadable`, nada é gravado). O padrão fica ao lado da fila; se o diretório da fila for gravável pelo grupo (umask 0002), aponte `olt_secrets.applied_file` para um diretório 0700.
- **Ausente**: vazio (a validade de até 1 h limita o risco).
- **Corrompido**: é movido para `<arquivo>.corrupt-<carimbo>`, o log avisa, e recomeça vazio. Pode apagar o `.corrupt-*` depois de olhar.
- **Ilegível** (permissão frouxa, erro de E/S): a entrega falha com `state_unreadable` e **nada é gravado** até consertar (`chmod 600`, dono certo). Se o armazém ficar inescrevível depois de o `credentials_file` já ter sido gravado, a entrega é reportada como `state_unreadable` (as credenciais já estão no arquivo; uma entrega nova regrava os mesmos valores).
- Para zerar de propósito: parar o Edge, apagar o arquivo, iniciar.

## Arquivos temporários e travas
Temporários `.fc-tmp-*` (0600, mesmo diretório) são removidos em toda falha e, se o processo morrer no meio, no próximo start e na próxima gravação. Cada `credentials_file` tem uma trava `<arquivo>.lock` (0600) ao lado.

## Reversão
- **Desligar só uma OLT**: remover `credentials_file` dessa OLT do `config.json` e reiniciar (o arquivo de credenciais fica no disco, sem uso; apague se quiser). Volta a valer a configuração estática, que precisa estar completa (`username`/`secret_file`/`snmp_community_file`).
- **Desligar tudo**: remover a seção `olt_secrets` **e todos** os `credentials_file` e reiniciar; o Edge para de publicar chave e de buscar entregas. Ou desligar a flag `fleet_secrets` na nuvem (o Edge só recebe 204/recusas).
- **Binário**: o binário anterior (`fibercore-edge.prev`) não conhece `olt_secrets`/`credentials_file` e **recusa** uma configuração que os tenha (campos desconhecidos são rejeitados). Para voltar o binário, remova antes essas chaves do `config.json`.

## Limites declarados (ADR-0045, R-1)
A assinatura da nuvem protege contra escrita direta no banco, não contra uma API comprometida: quem controla a API **e** a chave de assinatura pode entregar credenciais às OLTs que habilitaram `credentials_file` (risco de disponibilidade; não consegue ler credenciais já guardadas, nem redirecionar a conexão, porque endereço, chave do host e allowlist são locais).

## Implantação do binário novo (checklist; NÃO executado por este trabalho)
1. Backup do `config.json` e do binário atual (`fibercore-edge.prev`).
2. Compilar `cd agents/edge && go vet ./... && go test -race ./...` e o binário versionado com `-X main.version=...`.
3. Trocar o binário **sem** mexer no `config.json` e reiniciar: comportamento idêntico (feature off). Conferir heartbeat e coleta.
4. Só depois, adicionar `olt_secrets` e `credentials_file` por OLT (um `config.json` novo quebra o binário antigo).
5. Ordem do ADR: **Edge primeiro**, depois a nuvem, a flag por último.
