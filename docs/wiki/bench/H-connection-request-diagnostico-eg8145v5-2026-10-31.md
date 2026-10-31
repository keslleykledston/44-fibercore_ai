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
