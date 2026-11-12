# ADR-0045: Credenciais de OLT pela tela, cifradas até o Edge (fatia 2 do cadastro)

Status: Proposed (aguarda revisão do Codex e aceite do responsável) | Data: 2026-11-12 | Owner: Claude Code (implementação), Codex (revisão)

## Contexto

O ADR-0041 (D3) proíbe a nuvem de guardar credencial de OLT; a emenda 1 (2026-11-11) liberou só o endereço de gerência (não é segredo, devolvido mascarado) e deixou **login, senha e community SNMP** para uma fatia própria, "cifrados ponta a ponta com chave do Edge". O responsável pediu esses campos na tela de cadastro e mandou escrever e executar.

Fatos do código (2026-11-12):
- O Edge lê `secret_file` (senha SSH) e `snmp_community_file` **a cada sessão** (`config.ReadSecret` dentro de `Open`), exigindo arquivo modo 0600; o `username`, o `address`, o `host_key_sha256` e a `allowlist` são da configuração local (`config.json`).
- O Edge só conversa com a nuvem por HTTPS autenticado como conta de serviço (um Edge por conta), com `GET /v1/edge/jobs/next` e `POST …/result`.
- A API nunca precisa ler o segredo; só guardá-lo até o Edge buscá-lo.

## Decisão

**D1 — O segredo nasce cifrado no navegador e só o Edge o abre.** O navegador cifra com a chave pública do Edge; a API, o BFF, o banco, os backups e os logs só veem texto cifrado. Não existe rota que devolva segredo, nem cifrado, a nenhum cliente de usuário (só de escrita).

**D2 — O que continua local (defesa contra a própria nuvem comprometida).** Endereço, `host_key_sha256`, `allowlist` de rede e a lista de OLTs do Edge **não** são mudados pela nuvem. A entrega só preenche os arquivos de credencial de uma OLT **já configurada** no Edge, com o mesmo nome. Quem administra o Edge continua decidindo para onde ele pode conectar.

**D3 — Escopo da entrega (sem tocar na OLT).** Dois tipos: `ssh_login` (usuário + senha) e `snmp_community` (v2c). O Edge grava em arquivos locais já lidos por sessão: senha em `secret_file`, usuário em `username_file` (novo, opcional, modo 0600; se existir, vale sobre `username`), community em `snmp_community_file` (OLT com `transport:"snmp"`) ou em `last_down.snmp_community_file`. Se a OLT não tem o arquivo configurado, a entrega falha fechada (`target_not_configured`). SNMP v3 **não** é suportado pelo Edge hoje: a tela recusa `kind=snmp_community` quando o cadastro diz `v3`.

### Criptografia (contrato exato, interoperável Go ↔ WebCrypto)
- **Chave do Edge:** par ECDH **P-256** gerado no primeiro start; privada em arquivo 0600 (`seal_key_file`, dir 0700), nunca sai do host. Pública = ponto não comprimido (65 bytes), enviada em base64url (sem padding). `key_id` = primeiros 16 hex de SHA-256 do ponto. **Impressão digital** (para humanos) = primeiros 32 hex de SHA-256 do ponto, em 8 grupos de 4 separados por `-`.
- **Selagem (navegador):** par efêmero P-256; `ECDH(efêmera_priv, edge_pub)` → segredo de 32 bytes; `HKDF-SHA256(ikm=segredo, salt=vazio, info="fibercore-seal-v1|"+key_id)` → chave AES-256; **AES-256-GCM**, nonce de 12 bytes aleatórios; **AAD** = UTF-8 de `fibercore-seal-v1\n{tenant_id}\n{edge_id}\n{olt_name}\n{kind}\n{delivery_id}\n{key_id}\n{expires_at_unix}`. Blob = `0x01 ‖ efêmera_pub(65) ‖ nonce(12) ‖ ciphertext‖tag`, em base64url. Limite do blob: 2048 bytes.
- **Texto claro (JSON, antes de cifrar):** `{"kind":"ssh_login","username":"…","password":"…"}` ou `{"kind":"snmp_community","community":"…"}`. Tamanhos: usuário ≤ 64, senha ≤ 128, community ≤ 64; proibidos `\r`, `\n`, `\0`; vazio é recusado.
- **Vetores de teste:** um arquivo versionado gerado pelo Go e verificado em Python (formato) e Node/WebCrypto (decifra e cifra) para provar a interoperabilidade; o teste falha se qualquer lado mudar o formato.

### Confiança na chave pública (o ponto fraco, declarado)
Um atacante que controle a nuvem **e** o JS do web poderia trocar a chave pública e ler o segredo. Contenção: a chave do Edge nasce `pending` e **só vale após confirmação humana** da impressão digital, comparada com a exibida no host do Edge (`fibercore-edge seal-fingerprint`); qualquer chave nova volta a `pending` e invalida entregas pendentes. É a mesma classe de risco de qualquer UI web que envia segredos; **não** é proteção contra comprometimento ativo do servidor web. O que garante: banco, backups, logs e leitura passiva da nuvem nunca têm o texto claro.

### Fluxo e API
- Edge → nuvem: `POST /v1/edge/seal-key` `{public_key}` (idempotente; novo valor ⇒ `pending`).
- Nuvem → Edge: `GET /v1/edge/secret-deliveries/next` ⇒ `200 {id, olt_name, kind, key_id, expires_at, sealed}` ou `204` (arrendamento de 5 min; no máximo 1 em voo por Edge); `POST /v1/edge/secret-deliveries/{id}/result` `{outcome:"applied"|"failed", code}`. Resultado, sucesso ou falha, **apaga o blob** (`sealed = NULL`). Códigos: `bad_key_id`, `expired`, `aad_mismatch`, `decrypt_failed`, `invalid_payload`, `replayed`, `target_not_configured`, `write_failed`.
- Usuário: `GET /v1/fleet/edges/{id}/seal-key` (chave, impressão digital, estado), `POST …/confirm` `{key_id, fingerprint}`, `POST /v1/fleet/olts/{id}/secret-deliveries` `{delivery_id, kind, key_id, expires_at, sealed}` ⇒ 202, `GET …/secret-deliveries` (últimas 10: id, kind, estado, código; **nunca** o blob). `delivery_id` (UUID) e `expires_at` (≤ 1 h à frente) são escolhidos pelo navegador porque entram na AAD; a API os valida (formato, unicidade, janela) mas não os pode autenticar: quem autentica é o Edge ao abrir.
- Recusas da API: flag `fleet_secrets` desligada (403 `feature_disabled`), chave do Edge não confirmada ou `key_id` diferente da vigente (409), OLT de outro Edge/tenant (404), mais de 5 entregas pendentes por OLT (429), blob > 2048 bytes ou formato inválido (422, sem eco do valor).
- Expiração: entrega vencida tem o blob apagado de forma preguiçosa a cada chamada de entrega/consulta e é marcada `EXPIRED`; o Edge também recusa vencida (tolerância de relógio de 2 min).
- **Edge ao receber:** confere `key_id` e todos os campos da AAD contra a própria identidade; decifra; valida o JSON; grava o arquivo **atomicamente** (temporário 0600 no mesmo diretório + `rename`), depois informa o resultado. Guarda os últimos 1000 `delivery_id` aplicados em arquivo local para recusar repetição (`replayed`). Nenhum valor secreto em log, erro ou resultado.
- **Permissão e flag:** nova permissão `fleet:secrets` (risco R3, MFA recente conforme a política da plataforma) só para `isp_admin`; flag por provedor `fleet_secrets`, **desligada** por padrão e separada de `fleet_manager`. Toda ação é auditada **sem conteúdo** (OLT, `kind`, `delivery_id`, `key_id`, resultado).
- **Sem JavaScript, sem entrega:** os campos de segredo só existem na tela com JS ativo (WebCrypto disponível); sem ele, falha fechada com aviso.

### Reversibilidade e limites
Migração aditiva (tabela `olt_secret_deliveries` com RLS e colunas de chave em `edges`; a role da aplicação não lê o blob de volta fora da rota do Edge). Desligar a flag para a feature; o Edge sem a nova versão simplesmente não busca entregas. A entrega **não** troca a senha na OLT: só atualiza a cópia que o Edge usa. Rotação da chave do Edge exige nova confirmação.

## Alternativas descartadas
- **Guardar o segredo cifrado em repouso na nuvem (chave da nuvem):** a nuvem passaria a poder lê-lo (e a quem tiver o `.env`).
- **Cifrar só no servidor web/BFF:** o texto claro passaria pelo BFF e pela API.
- **Mudar a configuração do Edge pela nuvem (endereço, chave do host, allowlist):** uma nuvem comprometida poderia redirecionar o Edge; mantido local.
- **Senha por job assinado do motor de jobs:** o motor existe para escritas em dispositivo, com gates de homologação; aqui a escrita é só no armazenamento local do Edge.

## Consequências
- Edge e nuvem mudam juntos, nesta ordem de implantação: **Edge primeiro** (publica a chave e ignora o que não entende), depois a nuvem; a flag liga por último.
- O responsável precisa confirmar a impressão digital no primeiro uso e a cada rotação.
- Custo operacional: o campo "login" passa a poder viver em `username_file`; `username` no `config.json` continua valendo sem o arquivo.
