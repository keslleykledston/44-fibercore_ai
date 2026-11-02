# Homologação automatizada, sem retrabalho

## Níveis (por operação; nunca só por fabricante)
- **L0 CATALOGED**: modelo e documentação mapeados; sem acesso.
- **L1 DETECTED**: OID/modelo/firmware e transporte confirmados na OLT real.
- **L2 MONITORING_VALIDATED**: chassi/slots/PON/ONU contagens e quality conferidos com painel fabricante; golden fixture.
- **L3 PROFILE_PREVIEW_VALIDATED**: render de configurações determinístico, testes negativos, idempotência, impacto, diff e referências de profiles corretos.
- **L4 PROVISIONING_CERTIFIED**: autorizações explícitas, execução de bancada, read-back, rollback e aprovação dupla para ações disruptivas.

## Matriz de testes reutilizável (mínimo 22)
1. SSH/TLS hostkey; 2. SNMPv3 auth; 3. identity; 4. firmware; 5. OID; 6. board present; 7. slot empty; 8. PON 0-/1-based; 9. PON physical UP; 10. PON administratively off; 11. ONUs 0; 12. ONU online; 13. ONU offline; 14. ONU stale; 15. OLT unreachable; 16. CLI pager; 17. output locale; 18. truncated output; 19. hidden columns; 20. profile already exists; 21. conflicting profile id; 22. profile in use by other ONUs.

Para L4, adicionar 23. invalid VLAN; 24. ONU SN duplicate; 25. unauthorized user; 26. approval declined; 27. dry-run diff; 28. post-apply readback; 29. rollback/compensação; 30. audit no secrets.

## Fixture obrigatória
Para cada comando/capacidade, salvar `vendor__model__firmware__operation__case.txt` com saída **redigida**, `expected.json`, SHA-256 e documento fonte (revisão/data). Preservar disposição dos campos; mascarar senhas, IPs sensíveis, serial de assinante e nome dos clientes. A fixture é versionada no Git com licença revisada.

## Casos cross-vendor essenciais
- GPON / EPON / XGS-PON nunca compartilharem parser sem schema versionado.
- Endereço físico canônico `frame/slot/port` e `vendor_raw_path`; a UI exibe rotulagem nativa, e não renumera hardware.
- `ONU_DOWN` não implica `PON_DOWN`; contagens `null` quando incompletas, com `quality`/`collected_at`.
- Firmware novo não herda selo homologado automaticamente.

## Ciclo de lançamento
Catalogar -> adquirir manual -> criar fixture sintética -> driver read-only -> bancada -> L2 -> preview -> testes/rollback -> L4 somente com aprovação -> piloto por POP -> liberar feature flag.
