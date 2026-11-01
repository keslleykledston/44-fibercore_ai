# Connection Request da ONT de bancada — diagnóstico (somente leitura) — 2026-10-31

Escopo: SOMENTE a ONT de bancada (Huawei EG8145V5). Nenhuma escrita no ACS nem na ONT; endereços e credenciais mascarados ou omitidos. Executado no host do ACS com `sudo` (a conta do projeto está no grupo `sudo`; a nota anterior de "sem root" estava errada).

## Fatos observados
- O ACS responde 202 em 0,04 s a toda tarefa com Connection Request porque o próprio Connection Request falha.
- Reproduzido a partir do host do ACS (mesmo caminho do GenieACS): a URL de Connection Request da ONT (faixa 100.64/10, porta 7547) responde **401** com desafio digest (`realm` do gateway Huawei, `qop=auth`, MD5) e **continua 401 com a credencial que o ACS guarda**.
- O usuário guardado no ACS **é igual** ao que a ONT informa (lido por tarefa `getParameterValues` enfileirada sem Connection Request, 19:03 UTC): igual ao ID do dispositivo. A senha não é legível na ONT, então não pôde ser comparada.
- O último Inform por evento "6 CONNECTION REQUEST" desta ONT foi em 2026-10-30 05:12; a ONT reiniciou em 2026-10-30 06:34 e desde então nenhum.
- O ACS grava usuário (ID do dispositivo) e uma senha fixa por dispositivo na ONT todo dia pelo provision padrão `inform` (SetParameterValues em 2026-10-30 04:16 e 2026-10-31 04:18). Não há falhas (`/faults`) registradas.
- Debug do CWMP não está ligado (o arquivo configurado não existe).

## Conclusão e hipóteses (NÃO confirmadas)
A falha é de credencial (401), não de rede. Hipóteses para a senha divergir, sem prova: (a) a ONT aceitou a escrita com status "aplicar após reinício" e ainda não aplicou; (b) a ONT reverteu a senha para a de fábrica/configuração própria no reinício de 06:34; (c) a ONT guarda outra senha por configuração do OLT/OMCI.

## Próximo (precisa de autorização do responsável, é escrita em dispositivo)
F1: reenviar à ONT a MESMA credencial que o ACS guarda, por tarefa enfileirada, e repetir o teste de 401. F2: se continuar 401, reiniciar a ONT de bancada pelo caminho gated (H2) para aplicar. F3: conferir a senha na interface web da ONT.

## Execução do F1 (autorizado pelo responsável em 2026-10-31, bancada apenas)
- 1ª tentativa (reenvio do mesmo valor): **no-op**. O GenieACS não reenvia valor igual ao do cache; a tarefa saiu da fila sem requisição à ONT. Nada foi escrito.
- 2ª tentativa (valor temporário aleatório + retorno ao original; original guardado em arquivo 0600 de root, depois apagado com `shred`): no Inform de 19:23 UTC o ACS enviou **dois `SetParameterValues` reais** (temporário e, na mesma sessão, o original pelo provision `inform`); sem falhas, sem tarefas pendentes, cache do ACS igual ao original.
- **Resultado: a ONT continua respondendo 401** à credencial do ACS depois das escritas aceitas. Ou seja, a ONT aceita a escrita da senha de Connection Request mas não a usa (hipótese: só aplica após reinício, ou a senha efetiva vem de outra configuração). Causa ainda NÃO confirmada.
- Próximo: F2 (reinício da ONT de bancada pelo caminho gated H2, autorização de uso único) e/ou F3 (conferir a senha na interface web da ONT).

## Desfecho (2026-11-01): padrão do ACS adotado e Nokia corrigida
- **Huawei EG8145V5:** o Connection Request funciona pelo ACS desde a remoção da chave global `cwmp.connectionRequestAuth` (o GenieACS passa a usar a credencial por dispositivo gerada pelo provision `inform`); tarefa de leitura via ACS: HTTP 200 em ~0,6 s. Foi necessário, além disso, que a senha na interface da ONT fosse a gerada pelo ACS (o valor da interface prevalece sobre escritas por TR-069 nesse modelo).
- **ZTE F670L:** voltou a informar e o Connection Request funciona pelo ACS (HTTP 200 em 0,55 s) com a credencial por dispositivo.
- **Nokia G-1426G-A:** o Connection Request falhava (403 após autenticar, depois bloqueio temporário por tentativas falhas) com o usuário gerado a partir do ID do ACS (`…G%2D1426G%2DA…`, 33 caracteres, com `%`). **Hipótese que se confirmou:** o servidor HTTP da ONT não tolera o `%2D` no usuário do digest. Correção: o provision `inform` passou a usar, SÓ para o fabricante `ALCL`, o **número de série** (12 caracteres alfanuméricos) como usuário de Connection Request; os demais fabricantes continuam com o ID. Depois de o ACS gravar o novo usuário (SetParameterValues no Inform seguinte), o Connection Request da Nokia executou a tarefa de leitura em 0,54 s (HTTP 200).
- **Cuidado aprendido:** a Nokia **bloqueia temporariamente** (responde 403 até a requisição sem credencial) depois de tentativas com credencial errada. Testar só pelo caminho real do ACS e com intervalos de vários minutos.
- **Cópias de segurança (host do ACS, root, modo 0600):** a chave global antiga (`/root/.fc_cr_auth_backup.json`) e as duas versões anteriores do provision `inform` (`/root/.fc_inform_provision_backup.js` e `…_backup2.js`). Apagar com `shred` quando não houver mais interesse em reverter.
- **Exposição de credencial:** o valor de `cwmp.auth` do ACS foi impresso por engano em uma saída da sessão (máscara que não reconhecia o formato `AUTH("…","…")`, já corrigida). Recomendada a rotação do `cwmp.auth` (`docs/operations/GENIEACS_CWMP_AUTH_ROTATION.md`).
