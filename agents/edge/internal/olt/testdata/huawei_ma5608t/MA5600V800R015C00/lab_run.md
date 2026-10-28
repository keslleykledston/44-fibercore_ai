# Captura REAL: Huawei MA5608T, MA5600V800R015C00 (SPC100 HP1013)

- Data: 2026-10-28. Modo: leitura, 1 comando, shell interativo (pty) via SSH legado, acesso por salto (host do GenieACS).
- Comando: `display version` (+ um Enter que completa o prompt de parâmetros opcionais `{ <cr>|backplane<K>|frameid/slotid<S> }:`).
- Arquivo `display_version.txt` = fluxo bruto do terminal (eco do comando, prompt de parâmetros, saída, prompt final).
- Sanitização: nome de equipamento/site no prompt trocado por `OLT-TEST-1`; sem IPs, seriais, clientes ou datas de login.
- Paginação: não ocorreu neste comando.
- O que isto NÃO prova: parsers de `display ont info summary` / `optical-info` continuam contra fixtures sintéticas. Driver
  permanece `identified`; esta captura só valida `Identify` (modelo + firmware) e o transporte (shell, prompt, SSH legado).
- Achados do equipamento: ignora SSH exec; só oferece DH group1/group-exchange-SHA1, ssh-rsa, AES-CBC; prompt de usuário `NOME>`.

## Sessões de 2026-10-28 (PON 0/0/14, `enable` + `config` + `interface gpon 0/0`, só leitura)
- `board_0.txt` — `display board 0` (slots 0 e 1 GPON `H805GPFD`, 2 controladora, 4 e 5 energia).
- `ont_optical_info_14_all.txt` — `display ont optical-info 14 all` (3 ONTs online; colunas Rx, Tx, OLT Rx, temperatura, tensão, corrente).
- `ont_info_14_all_paged.txt` — `display ont info 14 all` com pager: **fluxo bruto do terminal** (inclui `ESC[37D`), uma tecla Espaço enviada, rodapé `In port ..., the total of ONTs are: 12, online: 3`.
- Ajuda do equipamento: `display ont info ?` (contexto gpon) lista só `portid<0,15>`; `display ont info 14 ?` lista `all` e `ontid<0,127>`.
- Sanitização: prompt → `OLT-TEST-1`; 12 SNs trocados por SNs fictícios de mesmo formato (mapeamento consistente); descrições (2ª tabela) com um valor trocado; sem IPs.
- Erros do operador/ferramenta durante a coleta (registrados): (1) a primeira tentativa usou a forma global `0/0/14` do driver MA5800 e foi rejeitada pela OLT; (2) uma sonda enviou `quit` com o pager ativo (o `q` interrompeu a paginação; o restante virou comando inválido rejeitado), sem efeito na configuração.
