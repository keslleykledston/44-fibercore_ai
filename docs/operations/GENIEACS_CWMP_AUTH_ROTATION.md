# GenieACS — autenticação CWMP e rotação de credenciais (rotação concluída para as ONTs de bancada em 2026-11-02)

**Estado observado (2026-10-30, somente leitura):** o ACS exige autenticação CWMP (`cwmp.auth`) e usa um par FIXO para o Connection Request (`cwmp.connectionRequestAuth`). Os valores não estão neste arquivo nem no repositório. Só a ONT de bancada tem as credenciais certas; as ONTs de produção aparecem como `DISCOVERYSERVICE` e falham com `Authentication failure`.

## O que é decisão e ação do responsável
1. **Política:** um par compartilhado por todas as ONTs (hoje) ou credenciais por dispositivo. Por dispositivo é o correto, mas exige que a OLT/ONT ou uma provisão do ACS entregue a credencial a cada ONT (o que o provedor controla, não este projeto).
2. **Entregar a credencial às ONTs de produção** (perfil CWMP na OLT/ONT, ou provisão): é o passo que reconecta as ONTs ao ACS. Sem ele, trocar o par só muda quem falha.
3. **Janela e reversão:** trocar `cwmp.auth` de uma vez desconecta toda ONT que ainda usa o par antigo. Faça em lotes (por OLT ou por faixa de serial) e mantenha o par antigo aceito até o lote terminar.

## O que dá para fazer pelo projeto (a pedido explícito, com `sudo` somente nos comandos abaixo)
- **Medir antes de mexer:** contar por dispositivo `Inform` aceito × `Authentication failure` no `genieacs-cwmp-access.log` (sem imprimir IPs), para saber quantas ONTs hoje funcionam.
- **Ensaiar na ONT de bancada:** trocar o par, atualizar a ONT de bancada e ver o Inform voltar; depois reverter.
- **Ler** o valor atual de `cwmp.auth`/`cwmp.connectionRequestAuth` só no terminal do responsável (nunca colar em chat ou arquivo): `sudo mongosh --quiet genieacs --eval 'db.config.find({_id:/cwmp\.(auth|connectionRequestAuth)/}).toArray()'`.
- **Aplicar** a nova configuração no ACS depois da aprovação do plano de lotes.

## Rotação (resumo)
1. Escolher o novo par e o escopo do lote.
2. Aceitar os DOIS pares durante o lote (verificar na bancada se a expressão do GenieACS suporta; se não suportar, usar uma janela curta).
3. Atualizar as ONTs do lote e confirmar Inform aceito pelo log.
4. Remover o par antigo só depois de zerar as falhas do lote; guardar o novo par fora do repositório (cofre).
5. Fazer o mesmo para a credencial de Connection Request; o Connection Request precisa também da origem coincidir com o endereço de ACS configurado na ONT (ver `EDGE_GENIEACS_LAB.md`).

## Andamento da rotação (2026-11-01, ordem do responsável)
- **Medição (somente leitura, 24 h):** só a Huawei EG8145V5 e a ZTE F670L de bancada informam com a autenticação aceita; as 32 falhas de autenticação vinham de um MikroTik que já falhava. Nenhuma ONT de produção usa o par atual: a rotação só afeta as ONTs de bancada.
- **Fase 1 APLICADA:** `cwmp.auth` agora é `AUTH(antigo) OR AUTH(novo)` (o motor de expressões do GenieACS 1.2.16 avalia cada `AUTH` como booleano). Backup 0600 da config `cwmp.*` no host do ACS (fora do repositório); o par novo está num arquivo 0600 local fora do repositório (nunca impresso). Provado: sem credencial e credencial errada → 401; as duas ONTs de bancada continuaram informando com o par antigo sem nenhuma falha. NÃO provado: que o par novo é aceito (só uma ONT configurada com ele prova).
- **Fase 2 (precisa de alguém na bancada):** configurar o par novo nas ONTs de bancada pela interface de cada uma (usuário/senha do ACS). Eu não escrevo isso nas ONTs: não existe operação de bancada aprovada para essa escrita (ADR-0030, catálogo fechado).
- **Fase 3 (só depois de ver Inform aceito com o par novo em cada ONT):** deixar `cwmp.auth` só com o par novo e apagar o backup e o arquivo local do par antigo/novo conforme a política de cofre. Reversão a qualquer momento: restaurar `cwmp.auth` do backup 0600.
- `cwmp.connectionRequestAuth` já foi tratado antes (credencial por dispositivo); não faz parte desta rotação.

## Fases 2 e 3 CONCLUÍDAS (2026-11-02)
- **Fase 2:** o responsável configurou o par novo na Huawei EG8145V5 e na ZTE F670L. As duas continuaram informando com sessão aceita e 0 falhas de autenticação no log do ACS.
- **Fase 3 APLICADA:** `cwmp.auth` agora é `AUTH(novo)`. Provado: sem credencial, par novo errado e par antigo errado → 401; o **par antigo exato → 401** (recusado); depois da mudança as duas ONTs de bancada informaram de novo (sessões aceitas só pelo par novo, até 03:34 UTC, depois do ACS reler a config). Reversão automática do script não foi necessária na tentativa que valeu.
- **Armadilha aprendida:** o GenieACS guarda um *snapshot* da configuração com revisão em cache compartilhado de até 300 s (`cwmp` relê a revisão a cada 5 s, mas só recalcula quando a chave expira). Uma gravação **direta no Mongo** só vale depois disso. Nas duas primeiras tentativas o par antigo ainda era aceito 30 s e 5 min depois da troca e o script reverteu sozinho; a terceira sondou o par antigo exato até ele dar 401 (60 s). Regra: depois de mexer em `cwmp.auth` pelo Mongo, **só declare efeito** depois de sondar a credencial removida até ela ser recusada.
- **Efeito colateral dos testes:** a sondagem com o par antigo exato (aceito enquanto o snapshot era velho) criou o dispositivo `FFFFFF-AUTHTEST-0` no ACS; foi apagado pelo NBI (`DELETE /devices/FFFFFF-AUTHTEST-0` → 200; o primeiro DELETE deu 503, transitório). Os `FFFFFF-fctest-*` são fixtures antigos de outra frente e não foram tocados.
- **Pendente do responsável:** guardar o par novo no cofre de senhas e só então apagar `~/.fibercore-cwmp-novo.json` (local) e os arquivos `~/.cwmp-config-backup-*` do host do ACS (contêm o par antigo, já recusado, e o `connectionRequestAuth` em uso). Não apaguei: são a única reversão. Rotação de ONTs de produção: não existe, nenhuma usa esse par.
