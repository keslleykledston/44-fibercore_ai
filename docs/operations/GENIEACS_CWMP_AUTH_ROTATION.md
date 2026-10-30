# GenieACS — autenticação CWMP e rotação de credenciais (plano; nada aplicado)

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
