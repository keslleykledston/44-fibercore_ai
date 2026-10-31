# Speed Diagnostics — checklist de ativação do FiberCore (complementa `reference/checklists/ROLL_OUT.md`, que é a cópia intacta do pacote)

Preencher **por modelo+firmware** antes de qualquer abertura além da bancada. Item não confirmado = não ativa.

## A. Por combinação `vendor / model / firmware / root (Device:2|IGD:1) / método`
- [ ] Evidência no registro de capacidades (`capability-set` com `evidence_ref` e `verified_at`) para `speed_test_download` e `speed_test_upload`
- [ ] Referência da WAN de serviço registrada pelo dono (instância/VLAN) e conferida com o sinal auxiliar do CPE; **não é a WAN de gerência**
- [ ] **Comportamento diante de 3xx registrado COM EVIDÊNCIA**: o CPE **segue** ou **não segue** redirecionamento (teste contra endpoint de laboratório que responde 3xx para um destino de captura sob controle do dono). O resultado entra no registro de capacidades da combinação, como operação própria `speed_test_redirect_probe` (`status` = `supported` se **não segue**, `unsupported` se **segue**), com `evidence_ref` (arquivo do ensaio: horário, id do ACS mascarado, resposta do destino de captura) e `verified_at`; sem essa linha a combinação é tratada como "segue"
- [ ] Se o CPE **seguir** o 3xx, ou se faltar a evidência: **ACL/firewall confirmado por escrito** na WAN de serviço, permitindo saída **somente aos nós de teste** (origem = WAN de serviço da ONT; destino = IPs/portas dos nós), com a regra e quem a aplicou anotados
- [ ] Tamanho máximo de arquivo e tempo mínimo (≥ 3 s) do modelo anotados; `TestBytesSent` disponível ou não

## B. Por nó de teste (Core e, se houver, Internet)
- [ ] GET e **PUT** funcionam; PUT descarta o corpo (nada gravado em disco)
- [ ] **Não redireciona** (sondagem do Edge e teste manual com resposta 3xx desligada)
- [ ] Sem compressão/CDN/cache; capacidade útil acima do plano testado; CPU/interface/disco monitorados
- [ ] ACL de origem fixa; sem token na URL; nó fora do domínio de roteamento do provedor (Internet) ou em `core_cidrs` (Core)

## C. Ambiente
- [ ] Config do Edge validada (esquema/porta fixos, IP fixado no carregamento, sem faixa especial; `INTERNET` sem destino privado)
- [ ] Autorização de bancada de uso único aberta (janela curta), ator que autoriza ≠ quem pede ≠ quem aprova
- [ ] Flag `speed_diagnostics` desligada até o aceite; `bench_writes` só para o alvo de bancada
- [ ] Piloto real: 3 repetições em baixa carga, Core e Internet, confronto com medição cabeada; caso negativo (bridge, CPE sem escrita, nó fora)
- [ ] Codex sem BLOCK; rollback documentado (desligar a flag; migração aditiva reversível)
- [ ] Responsável autorizou a ativação
