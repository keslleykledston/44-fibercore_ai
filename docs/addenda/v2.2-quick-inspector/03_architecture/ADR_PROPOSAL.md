# Mini-ADR proposta — reuso do EntityDetailDrawer para ONU

**Status:** PROPOSTA; não é uma ADR aprovada. Autoridade: ADRs existentes prevalecem.  
**Contexto:** Operadores precisam visualizar resumo ONU/ONT em inventário, árvore OLT/PON e NOC sem mudança de página.

## Decisão proposta
Adicionar variante ONU ao drawer contextual direito existente, alimentada por view model normalizado e autorização do backend. Miniatura SVG genérica primeiro; mapeamentos homologados depois. `ONU 360°` permanece rota completa. Sem backend próprio, sem persistência nova, sem write.

## Alternativas rejeitadas
1. Nova página de miniatura por dispositivo: navegação duplicada/latência cognitiva.
2. Modal central desktop: interrompe consulta à árvore/lista.
3. Novo serviço `device-visual`: alto custo/operação; desnecessário para P0.
4. Duplicar dados no frontend (OLT/ACS/ERP sem normalizador): aumenta inconsistência.

## Consequências
+ Reuso, escopo contido, rollback por feature flag, redução de clicks.  
- Precisa garantir controle de seleção, responsividade, autorização e fontes com tempos distintos.  
- Modelos vendor-specific ficam para homologação independente.

## Aprovação
Checar ADRs atuais antes de registrar novo número. Se compatível e não exigir mudança arquitetural, documentar como decisão de UI no PR sem produzir ADR desnecessária.
