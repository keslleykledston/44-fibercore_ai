---
title: "Como limitar uma pessoa a alguns sites ou OLTs (escopo)"
slug: "administracao/escopo-por-site-e-olt"
role: [isp_admin, access_manager]
status: draft
product_version: "0.1.0"
last_verified: "2026-11-14"
help_owner: "Plataforma FiberCore"
ui_route: "/administracao/equipe"
---

# Como limitar uma pessoa a alguns sites ou OLTs (escopo)

**Objetivo:** deixar um técnico ou operador ver só a rede de uma cidade (alguns sites ou OLTs), sem ver o resto do provedor.

**O que o escopo faz:** quem tem escopo **só lê a rede dentro do escopo** (as OLTs e os sites escolhidos e o que está ligado a eles: PONs, ONUs, incidentes, aparelhos). Ele **perde** clientes, equipe, auditoria, políticas e qualquer ação em equipamento. O que está fora do escopo **não aparece**, como se não existisse.

**Quem pode ter escopo:** Engenheiro, Operador NOC e Atendimento. Administrador, Gestor de acesso e Auditor precisam ver o provedor inteiro.

## Passo a passo

1. Em **Administração → Equipe e acessos**, na linha da pessoa, clique em **Escopo**.
2. Marque os **sites** (cada site inclui as OLTs dele, também as futuras) e/ou as **OLTs**.
3. Clique em **Salvar escopo**. Vale na próxima tela da pessoa, sem ela entrar de novo. A linha passa a mostrar **Restrito: N sites, M OLTs**.
4. Para devolver o provedor inteiro: **Escopo → Remover restrição**.

A pessoa vê no topo da Visão Geral o aviso **“Seu acesso é restrito a N OLTs”** e o menu mostra só o que ela pode usar.

## Cuidados
- Para dar a ela uma função que vê o provedor inteiro, **remova o escopo antes**.
- Mudanças de escopo ficam registradas na auditoria.

> Rascunho (sem capturas de tela ainda).
