# Levantamento do GenieACS existente (4WNET) — 2026-10-28

Método: login na UI do GenieACS com a credencial do `.env` e **apenas requisições GET** (`/api/devices`, `/api/presets`, `/api/provisions`, `/api/config`, `/api/faults`, `/api/users`). Nenhuma escrita, nenhum job, nenhum refresh. Credenciais nunca registradas aqui. Dados brutos ficaram fora do repositório.

## O que existe

| Item | Achado |
|---|---|
| Versão | GenieACS 1.2.16 |
| Exposição | 4 portas públicas no IP do concentrador: SSH (recusou a senha do `.env`), CWMP/TR-069 (`POST`-only, HTTP 405 em GET), UI do GenieACS e uma UI web antiga (2016) de outro equipamento. **O NBI (7557) não está exposto.** |
| Dispositivos | 44 no total |
| Presets | `inform`, `bootstrap`, `default` (padrão), `Disparar_Homologacao` (peso 10), `Preset_Audit` (peso 20) |
| Provisions | `inform`, `default`, `bootstrap`, `inform_bootstrap` (refresh de toda a árvore), `homologacao_ont_universal` (**escreve**), `auditoria_ont_leitura` (leitura + log de Rx Power) |
| Faults | 1: `script.TypeError` no dispositivo MikroTik de teste (provision acessa índice indefinido) |
| Usuários da UI | 4, todos `admin` (um deles é a integração do ERP Hubsoft) |

### Inventário de dispositivos

| Qtde | Fabricante / classe | Modelo de dados | Observação |
|---|---|---|---|
| 41 | `DISCOVERYSERVICE` | — | Dispositivos fantasma: varreduras externas se identificam na porta CWMP pública. Não são ONUs. |
| 1 | MikroTik hAP lite, SW 6.48.6 | `Device:2` | Dispositivo de teste. Inform a cada 300 s. |
| 1 | ACME Networks G3000E, SW G3000E-1.2.3 | `Device:2` | Dispositivo de teste/simulado. |
| 1 | `probe` (OUI 000000) | — | Sonda. |

**Não há nenhuma ONU/ONT Huawei, ZTE ou Nokia real cadastrada.** Portanto este GenieACS não fornece capturas reais para promover drivers de `identified` para `observed`. Os caminhos TR-098/TR-181 de Rx Power usados pelo provision de auditoria seguem não confirmados.

## Riscos encontrados (não corrigidos — GenieACS é do usuário, nossa postura é somente leitura)

| Sev. | Risco | Recomendação |
|---|---|---|
| ALTO | `cwmp.Auth = AUTH("admin","admin")` em porta CWMP pública. Qualquer cliente autentica. A presença de 41 fantasmas confirma. | Trocar por credencial forte por-CPE/ACS ou restringir a porta por ACL/VPN. |
| ALTO | O preset `Disparar_Homologacao` não tem `precondition` nem `events`: roda em todo inform e o provision escreve SSID e PSK de Wi-Fi fixos (a senha está em texto no script) em qualquer CPE que se declare Huawei/ZTE/Nokia. Um cliente falso autenticado com admin/admin recebe a senha; um CPE real teria o Wi-Fi do assinante sobrescrito a cada inform. | Desativar o preset ou limitar por tag/serial; tirar a senha do script. Rotacionar a PSK. |
| MÉDIO | `inform_bootstrap` pede `InternetGatewayDevice.` e `Device.` inteiros (refresh completo) — pesado em frota real. | Limitar a subárvores necessárias. |
| MÉDIO | Todos os usuários da UI são `admin`. | Perfil somente leitura para integrações (FiberCore, ERP). |
| BAIXO | Fault de script no hAP lite. | Proteger o acesso indexado no provision. |

## Impacto no FiberCore

- Edge Connector deve consumir **NBI** (porta 7557) por rede privada (o concentrador já tem L2TP/IPsec). A UI pública não é contrato estável; **não** integrar por ela.
- Nenhum job de escrita via GenieACS será habilitado (mantido em `HOMOLOGATED_WRITES` vazio).
- Antes de qualquer ONU real entrar: corrigir o preset de homologação acima, senão o próprio GenieACS escreve na rede sem passar por aprovação/auditoria do FiberCore.
- Para promover drivers a `observed` ainda é necessário capturar saídas reais de OLT (firmware exato) ou ONUs reais registradas.
