# Pedido de capturas de OLT (para promover drivers de `identified` a `observed`)

Hoje os parsers Huawei/ZTE foram escritos contra **fixtures sintéticas** (`agents/edge/internal/olt/testdata/README.md`). Sem saída real, o nível fica `identified` e nada é habilitado. Se o formato real divergir, corrijo o parser com a captura real, não o contrário.

**Só leitura.** Usuário de visualização na OLT. Nenhum comando de configuração. Rodar manualmente por SSH e salvar a saída sem reformatar (preservando colunas, espaços e quebras de linha), **sanitizada** conforme abaixo.

## Quais equipamentos
Uma captura por **modelo de OLT + versão exata de firmware** em uso (ex.: Huawei MA5800-X7 R018, ZTE C300 V2.1). Se houver vários firmwares do mesmo modelo, uma por firmware. Começar pelos mais numerosos na rede.

## Comandos (os comandos que os drivers executam; allowlist em `huawei.go`/`zte.go`)

| Fabricante | Comando | Observação |
|---|---|---|
| Huawei | `display version` | modelo + firmware |
| Huawei | `display ont info summary <F/S/P>` | uma porta PON por captura |
| Huawei | `display ont optical-info <F/S/P> all` | mesma porta |
| ZTE | `show version` | modelo + firmware |
| ZTE | `show gpon onu state gpon-olt_<F/S/P>` | |
| ZTE | `show gpon onu baseinfo gpon-olt_<F/S/P>` | |
| ZTE | `show pon power onu-rx gpon-olt_<F/S/P>` | |

Se o comando exigir outro modo/forma na sua versão (ex.: entrar em `config` ou `interface gpon F/S`), **capture o que funciona e anote**; eu ajusto o driver.

## Quais portas PON
1. Uma PON **com ONUs em estados variados**: online, LOS, falta de energia (dying gasp), offline, e se existir autenticação falha.
2. Uma PON **vazia** (sem ONU).
3. Uma PON com **muitas ONUs** (≥ 32, para ver paginação).
4. Se der: duas ONUs com `Rx` ausente/`N/A`.

## Paginação (limite conhecido)
O Edge **não** executa ajustes de terminal (`scroll`, `terminal length`): estão fora da allowlist e continuarão fora. O driver **não consegue** avançar páginas, mas agora **falha fechado**: se a saída contiver um prompt de paginação (`---- More ( Press 'Q' to break ) ----`, `--More--`, `press any key`), a coleta daquela OLT é descartada com `ErrPaginated` e nenhum inventário parcial é enviado (antes, uma lista cortada seria enviada como PON completa). Na prática a OLT precisa responder sem paginação para a conta de leitura. Por isso:
- Capture a saída **como o Edge a veria** (conta de leitura nas configurações dela). Se a saída vier truncada ou com `---- More ----`, **envie assim mesmo e avise**: isso é uma lacuna do driver a corrigir (com testes), não algo a contornar na captura.
- Se, para obter a saída completa, você precisar ligar/desligar paginação manualmente, anote no `lab_run.md` que foi um ajuste manual fora do fluxo do Edge.

## Sanitização (antes de enviar)
- Trocar números de série/GPON SN por valores inventados **mantendo formato e tamanho** (mesma mistura de letras/dígitos), de forma consistente (mesmo SN real → mesmo SN fictício em todos os arquivos).
- Remover/trocar nomes de cliente, descrições, IPs, MACs, nomes de OLT/site, senhas e comunidades SNMP. Manter posições `F/S/P`, ONT-IDs, estados e valores ópticos.
- Revisar manualmente prompts, banners, mensagens de login/aviso legal e qualquer campo não listado acima (hostname, localização, contatos, datas/horas que identifiquem o site, descrições livres) e remover/trocar antes de commitar. Em dúvida, remover.
- Manter fabricante, modelo, firmware, `F/S/P`, ONT-ID, estados e valores ópticos (necessários ao parser); se a combinação de porta + estados puder identificar um assinante/site, trocar a numeração de forma consistente e anotar.
- Não enviar `display current-configuration`/`show running-config`.
- Nada vai ao repositório antes dessa revisão; capturas não sanitizadas ficam fora do Git.

## Onde colocar
`docs/engineering/captures/<fabricante>_<modelo>/<firmware>/` com um arquivo por comando (`display_version.txt`, `ont_info_summary_0-1-0.txt`, …) e um `lab_run.md` com: data, modelo, firmware exato, quem executou, porta usada, se a paginação estava ligada. Formato exigido em `docs/engineering/DRIVER_SDK_INTERFACE.md`.

## Alternativa (sem você copiar nada)
Autorize explicitamente **uma** OLT de laboratório/baixo risco e informe o acesso (em seção própria do `.env`, nunca no chat). Eu executo apenas os comandos da tabela acima, pela própria allowlist do Edge (budget por OLT, sem escrita), sanitizo e registro. Sem essa autorização expressa não toco em OLT real.

## GenieACS (ONUs via TR-069)
Se já houver ONU real: configurar o ACS com a credencial CWMP nova e me avisar. Eu leio, por GET, **apenas os nomes** dos parâmetros (sem valores) de uma ONU por modelo/firmware, para confirmar os caminhos de Rx Power e dados de WAN/Wi-Fi.
