# Captura real, somente leitura, de OLTs de clientes (2026-11-14)

Evidência de bancada para o roteiro de homologação (`docs/engineering/DEVICE_CATALOG.md`, runbooks em `apps/api/app/knowledge_data/runbooks/`). **Sem endereço, porta, usuário, senha, nome de equipamento, serial ou MAC**: tudo mascarado (`SERIAL-XXXX`, `MAC-XX`, `IP-XX`, `<host>`). Credenciais passadas só por entrada padrão a um script descartável fora do repositório; nada gravado.

## Como foi feito
- De **este servidor** (não pelo Edge: a plataforma ainda não tem driver para estes fabricantes, ver "Lacunas"), **um login por equipamento** (sem tentativa repetida de senha) e **somente comandos de leitura** e de ajuda (`?`). Nunca `enable`, `config`, `system-view`, `commit`, `reload`, `systemreboot`, `restore`, `set2default`, `clear`, `delete` ou `set`.
- Alcançabilidade (TCP): 9 destinos; 7 abriram; os 2 da FW NETWORK (SSH 61321 e Telnet 8623) **não respondem deste servidor** (recusa imediata: provável filtro de origem; liberar o IP de saída do servidor ou testar pelo Edge).

## Resultado por equipamento
| Cliente | Equipamento | Acesso | Plataforma identificada |
|---|---|---|---|
| WA TELECOM | DATACOM1 | SSH OK | Datacom DmOS, DM4612 (8GPON), firmware 7.2.x |
| WA TELECOM | DATACOM2 | SSH OK | Datacom DmOS, DM4612 (8GPON), firmware 9.6.x (**outro equipamento**, mesmo modelo) |
| WA TELECOM | VSOL | **mesma porta que DATACOM2** | **sem teste**: a entrada repete IP e porta do DATACOM2 (provável erro de cadastro; informe a porta real da VSOL) |
| FW NETWORK | DATACOM - SAO JOSE | inalcançável deste servidor | sem teste |
| FW NETWORK | INTELBRAS - RAIO DE SOL | inalcançável deste servidor | sem teste |
| GL CONNECT | DATACOM1 | SSH OK | Datacom DmOS, DM4615 (16GPON), firmware 8.2.2 |
| ARAUJO | DATACOM1 | SSH OK | Datacom DmOS, DM4610 HW2 (8GPON) |
| ARAUJO | HUAWEI | SSH OK, **modo usuário** | Huawei MA5800-X2, MA5800V100R022C11 |
| JGA | HUAWEI | SSH OK, **modo usuário** | Huawei MA5800-X2, MA5800V100R024C11 |
| ASANET | INTELBRAS ITAP 8820i | **Telnet** OK | Intelbras OLT 8820i (software 2.112) |

Observação: o nome configurado nos dois equipamentos da WA TELECOM sugere outra empresa; confira o cliente do cadastro.

## Comandos homologados (execução real, leitura)
| Fabricante | Comando | Serve para | Estado |
|---|---|---|---|
| Datacom DmOS | `show inventory` | modelo, cartões, serial, MAC | executado em 4/4 |
| Datacom DmOS | `show platform` | modelo e **firmware** por slot | executado em 4/4 |
| Datacom DmOS | `show system` | relógio, uptime, último reinício, CPU | executado em 4/4 |
| Datacom DmOS | `show interface gpon \| nomore` | estado físico e banda por PON | executado em 4/4 |
| Datacom DmOS | `show interface gpon 1/1/N onu \| nomore` | **ONUs da PON** (id, serial, estado operacional, nome) | executado (GL CONNECT) |
| Datacom DmOS | `show interface gpon 1/1/N discovered-onus` | ONUs não autorizadas | existe (ajuda); **a executar numa PON com ONU pendente** |
| Datacom DmOS | `show alarm \| nomore` | alarmes ativos | executado em 4/4 |
| Huawei MA5800 | `display version` (pede `<cr>`) | versão/patch/produto | executado em 2/2 |
| Intelbras 8820i | `card stats` | CPU, memória, uptime, versão | executado |
| Intelbras 8820i | `shelfctrl monitor` | temperatura, ventoinhas, uptime | executado |
| Intelbras 8820i | `olt show port` | **óptica por PON** (Tx/Rx, temperatura, tensão) | executado |
| Intelbras 8820i | `alarm show` | alarmes | executado |
| Intelbras 8820i | `interface show` | interfaces de gerência | executado |

Particularidades que um driver precisa tratar: DmOS aceita `| nomore` (sem paginação) e o prompt é `<host>#`; Huawei em modo usuário pede `<cr>` após `display version` e **os demais `display` úteis exigem `enable`** (elevação de privilégio, só leitura; **precisa de autorização do dono**, não foi usada); Intelbras **não tem `show`** de topo (comandos são `card`, `olt show`, `shelfctrl`, `alarm show`, `onu ...`), mantém o texto digitado após `?` (limpar a linha com Ctrl-U antes do próximo comando), usa `login`/`Password` por Telnet e imprime banner e avisos coloridos (códigos ANSI) a cada login.

## Lacunas para a plataforma (honestas)
1. O **Edge só opera Huawei e ZTE por SSH** (`allowed_vendors`) e **recusa Telnet**; **não há driver** para Datacom DmOS, VSOL nem Intelbras. Sem driver, "consultas pela plataforma" para estes fabricantes não existem; esta captura é a matéria-prima para os drivers (parser golden com caso negativo, paginação, timeout).
2. Por política do projeto, uma OLT só passa de `identified` a `observed` com a captura **de bancada** do comando exato sem escrita, saída sanitizada e parser golden: faltam os parsers.
3. Huawei MA5800 (JGA, ARAUJO): `enable` pendente de autorização.
4. Intelbras: `onu ...` tem subcomandos (`find`, `gemports`, `gtp`...) ainda não executados; falta achar o equivalente a "lista de ONUs".
5. VSOL: sem captura (entrada duplicada). FW NETWORK: sem alcance deste servidor.

## Amostras sanitizadas
### DmOS: inventário
`show inventory`
```
show inventory
 Chassis             : 1
 Product model       : DM4615

  Chassis/Slot       : 1/1
   Product model     : 16GPON+4GT+4XS
   Part number       : 800.5305.51
   Serial number     : XXXX
   Product revision  : 51
   PCB revision      : Unknown
   Hardware version  : 0
   Operat. temp.     : 0 - 65 Celsius degrees
   Base MAC address  : MAC-XX

   Interface gigabit-ethernet 1/1/1
    MAC address      : MAC-XX
    Port type        : Electrical

   Interface gigabit-ethernet 1/1/2
    MAC address      : MAC-XX
    Port type        : Electrical

   Interface gigabit-ethernet 1/1/3
    MAC address      : MAC-XX
```

### DmOS: plataforma e firmware
`show platform`
```
show platform
Chassis/Slot  Product model      Role     Status        Firmware version
------------  -----------------  -------  ------------  ----------------------
1             DM4615             -        -             Not available
1/1           16GPON+4GT+4XS     Active   Ready         8.2.2-003-1-g2df4ad7b5a
1/FAN         DM4610-FAN         None     Ready         Not available
1/PSU1        PSU-125-AC         None     Ready         Not available

<host>#
```

### DmOS: sistema
`show system`
```
show system
Clock:  2026-11-14 14:47:53 UTC+0 
Uptime: 14:47:53 up 366 days, 17:09,  1 user,  load average: 0.40, 0.48, 0.50

Last reboot reason: Reboot requested by user 'admin'
Chassis/Slot: 1/1

   CPU load information:
   ---              5 seconds   1 minute  5 minutes
   active                 24%        21%        22%
   idle                   76%        79%        78% 

    CPU core 0 information:
    ---              5 seconds   1 minute  5 minutes
    user                   15%        14%        14% 
    system                  7%         7%         7% 
    nice                    0%         0%         0% 
    wait                    0%         0%         0% 
    interrupt               0%         0%         0% 
    softirq                 0%         0%         0% 
    active                 22%        21%        22%
    idle                   78%        79
```

### DmOS: PONs
`show interface gpon 1/1/1 ?`
```
show interface gpon 1/1/1 ?
Possible completions:
  brief             Display table information of GPON interfaces
  discovered-onus   Display GPON interfaces discovered ONUs
  onu               Add an ONU to PON link
  statistics        Display GPON interface statistics
  |                 Output modifiers
  ---
  <cr>
<host># show interface gpon 1/1/1 

Physical interface   :  gpon 1/1/1, Enabled, Physical link is Up
Link-level type      :  GPON
Logical reach        :  0-40 km
Downstream FEC       :  Enabled
Upstream FEC         :  Enabled
Transceiver type     :  sps-43-48h-hp-cde
Allocated upstream bandwidth
    Fixed + Assured  :  0          kbit/s
    Fixed            :  0          kbit/s
    Assured          :  0          kbit/s
    Max              :  22138880   kbit/s
    Overhead         :  660        kbit/s (20 ONUs)
Available upstream bandwidth
    CBR   BW         :  609600     kbit/s
    Total BW         :  1202752    kbit/s
OLT-
```

### DmOS: ONUs de uma PON
`show interface gpon 1/1/1 onu | nomore`
```
show interface gpon 1/1/1 onu | nomore
  Itf     ONU ID   Serial Number   Oper State   Software Download State      Name
--------  ------   -------------   ----------   --------------------------   ------------------------------------------------
1/1/1     0        SERIAL-XXXX    Up           None                                                                         
1/1/1     1        SERIAL-XXXX    Up           None                                                                         
1/1/1     2        SERIAL-XXXX    Up           None                                                                         
1/1/1     3        SERIAL-XXXX    Up           None                                                                         
1/1/1     4        SERIAL-XXXX    Up           None                                                                         
1/1/1     5
```

### DmOS: alarmes
`show alarm | nomore`
```
show alarm | nomore
Triggered on                 Severity Source                          Status   Name                           Description                             
---------------------------- -------- ------------------------------- -------- ------------------------------ -----------------------------------------
2026-09-27 03:05:21 UTC+0    MINOR    gpon-1/1/10/12                  Active   GPON_SUFi                      Start-up failure of ONU                  
2026-10-24 02:18:29 UTC+0    CRITICAL gpon-1/1/10/33                  Active   GPON_DGi                       Receive dying gasp of ONU                
2026-10-24 02:18:29 UTC+0    CRITICAL gpon-1/1/10/33                  Active   GPON_LOSi                      ONU Loss of signal                       
2026-11-06 20:21:59 UTC+0    CRITICAL gpon-1/1/10/44                  Active   GPON_LOSi                      O
```

### Huawei MA5800: versão
`display version`
```
display version 
{ <cr>|backplane<K>|frame<K>|frameid/slotid<S><Length 3-15>||<K> }: 

  Command:
          display version

  VERSION : MA5800V100R024C11
  PATCH   : SPC200
  PRODUCT : MA5800-X2

  Active Mainboard Running Area Information: 
  --------------------------------------------------
  Current Program Area : Area A 
  Current Data Area : Area A 

  Program Area A Version : MA5800V100R024C11 
  Program Area B Version : MA5800V100R024C11 

  Data Area A Version : MA5800V100R024C11 
  Data Area B Version : MA5800V100R024C11 
  --------------------------------------------------

  Uptime is 46 day(s), 19 hour(s), 58 minute(s), 59 second(s)

<host>>
```

### Intelbras: cartão
`card stats`
```
card stats
 ------ cpu % utilization ------    ------ memory (KB) ------       Card Memory         Uptime                    
 slot     idle       usage        %Used      Total       Avail       Status         ddd:hh:mm:ss     s/w version 
======   =======    =======      =======   =========   ==========   ==============  ==============  ==============
 1        78.1       21.9         36.0      1028352     539604      1 - OK          110:16:55:11    2.112
intelbras-olt>
```

### Intelbras: chassi
`shelfctrl monitor`
```
shelfctrl monitor
 Shelf                   Status   
----------------------------------------------------------
Uptime                   110 days, 16 hours, 55 minutes
 
 Temperature Sensor      Celsius(C)     
----------------------------------------------------------
Sensor 1                 31.125 C
Sensor 2                 30.250 C
Temperature reading      Normal
 
 Fans                    Status 
----------------------------------------------------------
Fan 1                    Detected
Fan 2                    Detected
Fan 3                    Detected
 
intelbras-olt>
```

### Intelbras: óptica por PON
`olt show port`
```
olt show port
GPON Temperature Voltage Tx Bias Current  Tx Power    Rx Power   End Of Life Status
==== =========== ======= =============== =========== =========== ==================
 1       35 C    3.205 V      14 mA       3.328 dBm  -31.549 dBm         OK        
 2       34 C    3.266 V      14 mA       3.295 dBm  -29.655 dBm         OK        
 3       38 C    3.221 V      14 mA       3.492 dBm  -26.383 dBm         OK        
 4       37 C    3.177 V      14 mA       3.382 dBm  -22.291 dBm         OK        
 5       40 C    3.177 V      11 mA       3.223 dBm  -29.586 dBm         OK        
 6       40 C    3.185 V      11 mA       3.055 dBm  -29.208 dBm         OK        
 7
```

### Intelbras: alarmes
`alarm show`
```
alarm show
************   Central Alarm Manager   ************
    Alarm Count     : 189
    History Count   : 100


********************************************** Alarms **************************************************
 Num        AlarmType            ResourceId               Info        AlarmSeverity         Date
------  ----------------  -----------------------  -----------------  -------------  -------------------
     2  System            abnormal reboot 0        2021-09-06 06:32   Critical       2026-07-26 18:00:30
     3  System            abnormal reboot 1        2021-09-06 18:51   Critical       2026-07-26 18:00:30
     4  System            abnormal reboot 2        2021
```
