# Captura REAL: Huawei MA5608T, MA5600V800R015C00 (SPC100 HP1013)

- Data: 2026-10-28. Modo: leitura, 1 comando, shell interativo (pty) via SSH legado, acesso por salto (host do GenieACS).
- Comando: `display version` (+ um Enter que completa o prompt de parâmetros opcionais `{ <cr>|backplane<K>|frameid/slotid<S> }:`).
- Arquivo `display_version.txt` = fluxo bruto do terminal (eco do comando, prompt de parâmetros, saída, prompt final).
- Sanitização: nome de equipamento/site no prompt trocado por `OLT-TEST-1`; sem IPs, seriais, clientes ou datas de login.
- Paginação: não ocorreu neste comando.
- O que isto NÃO prova: parsers de `display ont info summary` / `optical-info` continuam contra fixtures sintéticas. Driver
  permanece `identified`; esta captura só valida `Identify` (modelo + firmware) e o transporte (shell, prompt, SSH legado).
- Achados do equipamento: ignora SSH exec; só oferece DH group1/group-exchange-SHA1, ssh-rsa, AES-CBC; prompt de usuário `NOME>`.
