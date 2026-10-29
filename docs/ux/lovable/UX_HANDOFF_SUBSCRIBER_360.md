# Handoff de UX — Visão 360 do assinante (FC22-005)

Pedido ÚNICO em lote ao Lovable (política: UI/UX em lote, nunca segredos). Todos os dados abaixo são **sintéticos**.
O código do Lovable é só referência visual: a integração é feita à mão em Next.js/Tailwind com os tokens já validados por axe.

## Objetivo
Uma tela `/assinantes/[id]` que responde "como está a conexão deste cliente, e de onde vem cada informação?". Minimalista, futurista, inspirada em iOS (cartões de cantos suaves, translucidez leve, tipografia limpa), claro e escuro, português do Brasil, WCAG 2.2 AA.

## Princípios que a tela NÃO pode violar
1. Cada bloco mostra **fonte**, **quando foi observado** e **se está atualizado** ("Atualizado", "Dados defasados", "Sem coleta"). Defasado ≠ offline: é a idade do dado.
2. Estado geral do contexto, em texto + ícone (a cor nunca é o único indicador): `Completo`, `Parcial`, `Defasado`, `Desconhecido` — cada um com uma frase dizendo POR QUÊ.
3. **Nada de escrita na rede.** Reinício, troca de Wi-Fi etc. aparecem sempre bloqueados com o motivo "Operação ainda não homologada".
4. Abas só onde há dado: **Conexão**, **Óptica**, **Roteador (CPE)**, **Cliente**, **Ações**. Wi-Fi e Histórico NÃO têm fonte homologada: não mostrar aba; mostrar uma nota discreta "Wi-Fi e Histórico ainda não têm fonte homologada".
5. Dado pessoal mínimo: nome de exibição, "documento final 1234", situação do contrato. Sem CPF completo, sem endereço, sem telefone.
6. O vínculo ONU↔CPE só vale depois de confirmado por uma pessoa; antes disso é "sugestão (indício, não prova)".

## Dados (forma real da API, sintética)
```
status: complete | partial | stale | unknown ; onus_truncated: bool
customer: { display_name: "Cliente Exemplo", document_last4: "1234", contract_status: active|suspended|cancelled|unknown,
            provenance: { source: "erp:csv-demo", observed_at, quality: fresh|stale|unknown } }
onus[] (máx. 50): { serial: "DEMO0001", status: online|offline|los|dying_gasp, rx_dbm: -21.5, olt: "OLT-DEMO-01", pon_path: "0/1/0",
   provenance: { source: "olt_snapshot", ... }, incident: { suspected_cause: fiber_or_los|power|unknown } | null, incident_hidden: bool,
   cpe: { link: confirmed|suggested|none|unavailable, pending_suggestions, device: { vendor, model, firmware, protocols: ["tr069"] } | null,
          provenance: { source: "genieacs_nbi", ... } | null } }
```

## Estados obrigatórios (mostrar todos, desktop 1440×900 e mobile 390×844, claro e escuro)
- Completo; Parcial (uma ONU sem CPE confirmado); Defasado (ERP ou OLT velhos); Desconhecido (nenhuma ONU aprovada — "não afirmamos nada"); carregando (skeleton); erro; sem permissão (403); recurso desligado; vários ONUs (seletor) e truncado ("mostrando 50 de N").
- Incidente oculto: "Seu papel não permite ver incidentes" (nunca parecer "sem incidente").

## Entregáveis
Componentes tipados e acessíveis (foco visível, alvos ≥ 44 px, `prefers-reduced-motion`), tokens, e uma página de demonstração com os estados. Sem backend, sem autenticação, sem persistência, sem integrações.
