# Entrega do pacote único

1. Descompactar a pasta `FiberCore_AI_v2_5_COMPLETO_Provisioning_Profile_Studio` em diretório temporário junto ao workspace do FiberCore, sem sobrescrever paths do repositório.
2. Enviar ao Claude Code o texto de `prompts/04_PRIMEIRA_MENSAGEM.txt`; ele lerá `prompts/01_CLAUDE_CODE_MASTER.md`, `README_START_HERE.md`, documentação e contratos.
3. Enviar o mesmo pacote (ou seu checkout) ao Codex e solicitar revisão conforme `prompts/02_CODEX_REVIEW.md`.
4. Dar ao Lovable o arquivo `prompts/03_LOVABLE_UX.md` e os docs de UX. Handoff implementável em Next.js, não mock isolado definitivo.
5. Fluxo de implementação deve ser GAP → ADR/backlog → read-only/mock → UI → simulação → homologação de driver em LAB → aprovação e escrita autorizada → pós-check/documentação.
6. **Não compartilhar credenciais de OLT/HubSoft** nem habilitar escrita automaticamente na instalação.

Este pacote não altera o GitHub por si só. O Claude deve integrar através de PRs revisáveis e declarar o que de fato foi implementado.
