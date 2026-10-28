# Memória local, contexto e wiki durante a construção

## Objetivo

Desenvolvimento longo, multiagente, sem depender da memória de sessão. **Git é a fonte auditável**. Obsidian/BookStack/MkDocs são camadas de visualização; contexto operacional local de Claude/Codex é efêmero ou cache; nenhuma decisão pode existir só na conversa do agente.

## Diretórios canônicos (no repo)

- `docs/wiki/` wiki MkDocs Material (MD portável), navegação por módulo/feature/runbooks/FAQ;
- `docs/wiki/adr/` decisões imutáveis por ADR numérica;
- `docs/wiki/CHANGELOG.md` release e breaking changes;
- `docs/wiki/KNOWN_ISSUES.md` limites comprovados, incompatibilidades;
- `docs/wiki/DECISIONS.md` registro de decisões abertas/fechadas;
- `docs/wiki/IMPLEMENTATION_STATUS.md` percentual por **critério verificável**, não percepção;
- `docs/wiki/TEST_EVIDENCE.md` comandos/testes executados + commit SHA + ambiente;
- `.agent-context/PROJECT_STATE.md` resumo ativo <= 2k palavras com links;
- `.agent-context/NEXT_ACTIONS.md` o que fazer em próximo turno;
- `.agent-context/COMPONENT_MAP.md` arquivos/owners/contratos;
- `.agent-context/WORK_SESSION_LOG.md` resumos curtos por sessão.

**Opcional:** sincronizar com vault Obsidian local do ambiente, mas não usar caminho absoluto do computador do desenvolvedor nos scripts padrão. Scripts podem consultar `FIBERCORE_WIKI_SYNC_DIR` se explicitamente definido.

## Regra de atualização atômica por PR

Claude escreve código e testes; antes do PR atualiza status, changelog relevante, ADR se decisão nova, documentação API/driver, fixture, readme por módulo, limitações, memory checkpoint. Codex verifica diff vs contrato e registra `PASS/BLOCK/WARN` + justificativa. Somente então merge, sem bypass automático.

## Checklist de sessão de Claude

**Ao iniciar:** ler `README_START_HERE.md`, `prompts/01_CLAUDE_CODE_MASTER.md`, PROJECT_STATE, NEXT_ACTIONS, ROADMAP, última ADR e últimos commits. Não reler todo repo indiscriminadamente; usar índice e recorte de arquivos.

**Antes de codar:** anunciar hipótese, riscos, caminho vertical, contratos e testes previstos; se assunto afeta segredos/rede real, pedir aprovação.

**Durante:** commits pequenos e reversíveis, mocks inicialmente, docs-as-code após cada milestone; não inventar testes/homologação.

**Ao encerrar:** criar checkpoint de progresso incluindo mudanças, artefatos, testes executados com resultados, descobertas, riscos, próxima tarefa e instrução retomada.

## Instruções da memória local do desenvolvedor

Pode utilizar memória local-first do agente (por exemplo Obsidian/SQLite/FTS5 conforme infraestrutura), mas o repositório não pode depender de serviço externo de memória para compilar/rodar. Indexação de arquivos permitidos e não sensíveis, com exclusão de `.env*`, keys, tokens, customer PII, produção e dumps. Se for criada uma base de vetores, documentar path, recuperação, backup e purge por tenant.

## Glossário obrigatório

- ONU/ONT: equipamento PON; CPE: dispositivo sob TR-069/USP (pode coexistir com ONT).
- ACS: GenieACS TR-069; USP Controller: TR-369; Edge: proxy local executando operações tipadas.
- OLT read-only vs CPE remote management são domínios distintos.
- `module unhealthy` != `device offline`; `NBI task queued` != `operation verified`.
