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

## Sessão de 2026-10-28 (cobertura ampla): 32 PONs das placas 0 e 1 + `register-info`
- Autorizado pelo dono: ler todas as PONs (`display ont info <0..15> all`) das placas 0 e 1 e `display ont register-info 14 <0|7>`; Espaço como única tecla no pager (até 5 páginas).
- Novas fixtures sanitizadas: `ont_info_5_all_paged.txt` (60 ONTs, 5 páginas), `ont_info_12_all.txt` (6 ONTs, sem pager), `ont_info_s1_4_all_paged.txt` (2ª placa, 53 ONTs, 4 páginas), `register_info_14_0_offline_dying_gasp.txt`, `register_info_14_7_online.txt`.
- Sanitização: SNs trocados (mapa consistente, 119), prompt → `OLT-TEST-1`, **coluna Description neutralizada** (texto livre que identifica assinantes), datas do `register-info` trocadas por datas fictícias, vendor-id do SN trocado.

## Mapa da causa de queda (SNMP × CLI), 2026-10-28
`display ont register-info 14 <ont>` lido em 10 ONTs offline da PON 0/0/14 e cruzado com `46.1.24` por SNMP: 13 = `ONT dying-gasp`, 2 = `ONT LOSi/LOBi alarm`, 1 = `ONT link-down` (10/10 coerentes). O histórico por ONU traz várias quedas com causas diferentes; o código SNMP corresponde à mais recente. Dados brutos ficam fora do Git.
