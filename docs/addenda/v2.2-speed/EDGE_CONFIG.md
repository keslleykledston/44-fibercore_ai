# Speed Diagnostics — configuração local do Edge (exemplo)

Só no servidor do Edge (`/etc/fibercore-edge/config.json`, modo 0600). **Nada disto vai para a nuvem, para o repositório com valores reais, para o Lovable ou para a memória.** Os endereços abaixo são de documentação; troque pelos do provedor.

```json
{
  "jobs_enabled": true,
  "allowed_operations": ["collect", "refresh", "speed_test_download", "speed_test_upload"],
  "allowlist": ["<host-do-ACS>:<porta-NBI>", "<ip-do-no-core>:8080"],
  "bench": {
    "bench_writes_enabled": true,
    "devices": [
      {"oui": "00259E", "product_class": "EG8145V5", "serial": "<serial-da-bancada>",
       "speed_wan_interface": "InternetGatewayDevice.WANDevice.1.WANConnectionDevice.<n>.WANIPConnection.<m>"}
    ]
  },
  "speed": {
    "enabled": true,
    "core_cidrs": ["<prefixo-do-core>/16"],
    "endpoints": [
      {"id": "core-sp-1", "kind": "CORE", "host": "<ip-do-no-core>", "port": 8080}
    ]
  }
}
```

Regras (o Edge não sobe se alguma falhar):
- `speed.enabled` exige a seção `bench` ligada e `speed_test_download`/`speed_test_upload` em `allowed_operations`; essas operações sem a seção também são recusadas.
- `host` é IP literal. `CORE` precisa estar dentro de `core_cidrs`; `INTERNET` não pode ser privado/CGNAT/ULA/documentação. Loopback, link-local, metadados, multicast e reservados nunca valem.
- Cada `host:port` de destino também precisa estar em `allowlist` (a sonda de saúde é uma conexão de saída).
- `speed_wan_interface` é a WAN de **serviço** do aparelho (não a de gerência), em um dos dois formatos aceitos; sem ela o aparelho é recusado para teste de banda.
- O nó de teste atende `GET /health` (200, corpo exato `ok`), `GET /dl/<perfil>` (`10mb`, `50mb`, `200mb`) e `PUT /ul/<perfil>`, **sem redirecionar nunca** (item de aceite do nó). A ACL/firewall de saída da WAN de serviço, ou a evidência de que o aparelho não segue 3xx, é item do checklist `ROLL_OUT_FIBERCORE.md`.
- O responsável cria os destinos lógicos na nuvem com `speed-endpoint-set <tenant> <id> <rótulo> CORE|INTERNET <região> on|off` (sem endereço) e registra a evidência no registro de capacidades (`capability-set … speed_test_redirect_probe|speed_test_egress_acl …`).
- Ordem de implantação: **Edge primeiro, depois a nuvem**. Cada execução real exige nova autorização de uso único (`bench-authorize … --speed-target <id> --speed-profile <perfil>`).
