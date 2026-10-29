# GenieACS — fechar o NBI (runbook para quem tem root)

**Estado (2026-10-29, inspeção somente leitura + autorização do responsável para corrigir):** o NBI (7557) responde sem autenticação e escuta em todas as interfaces; a UI (3000), o FS (7567) e o CWMP (7547) também. O NBI **escreve** no GenieACS.
**Por que não foi aplicado por mim:** a conta SSH disponível ao projeto não tem root (`sudo` nem está instalado) e o arquivo de ambiente do serviço pertence ao usuário do serviço (modo 0600). Nada foi alterado no GenieACS. Isto é um passo para um administrador com root.

**O Edge não depende da exposição:** ele roda NO host do GenieACS e lê `http://127.0.0.1:7557` (ver `EDGE_GENIEACS_LAB.md`). Fechar o NBI para fora não o afeta.

## Antes
1. Descubra quem usa o NBI hoje (integrações antigas, scripts, outro painel): `ss -tn state established '( sport = :7557 )'` por um período representativo e o log do serviço. Se algo externo depender dele, migre para o Edge ou para um proxy autenticado antes de fechar.
2. Mantenha 7547 (CWMP) alcançável pelas ONTs; ele não deve ser fechado.

## Aplicar (root)
1. No arquivo de ambiente do serviço NBI (o `EnvironmentFile` de `genieacs-nbi.service`): `GENIEACS_NBI_INTERFACE=127.0.0.1`.
2. `systemctl restart genieacs-nbi`.
3. Firewall (defesa em profundidade, mesmo com o bind em loopback): `ufw deny 7557/tcp` (e restringir 3000 e 7567 à rede de gestão: `ufw allow from <rede-de-gestao> to any port 3000 proto tcp`, depois `ufw deny 3000/tcp`).
4. Se um dia o NBI precisar ser alcançado de fora: só por proxy reverso com TLS **e** autenticação, nunca direto.

## Verificar
- `ss -ltnp | grep 7557` mostra apenas `127.0.0.1:7557`.
- De outra máquina: `curl -m 5 http://<host>:7557/devices` → conexão recusada/timeout.
- No host: `curl -s http://127.0.0.1:7557/devices?projection=_id | head -c 100` continua respondendo.
- O Edge segue enviando: `last_heartbeat_at` da edge `edge-genieacs-lab` continua avançando no LAB.

## Reverter
Remover/voltar `GENIEACS_NBI_INTERFACE`, `systemctl restart genieacs-nbi`, `ufw delete deny 7557/tcp`.

## Outras exposições observadas (mesma janela)
SSH do host acessível; a porta CWMP aceita qualquer Inform sem credencial (por isso existem 37 identidades `DISCOVERYSERVICE`): configurar autenticação CWMP e rotacionar credenciais é decisão do responsável.
