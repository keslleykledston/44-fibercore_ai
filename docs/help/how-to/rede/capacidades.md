---
title: "Como ver as capacidades por modelo"
slug: "rede/capacidades"
role: [isp_admin, engineer, noc_n2, noc_n1, support]
status: draft
product_version: "0.1.0"
last_verified: "2026-10-30"
help_owner: "Plataforma FiberCore"
ui_route: "/dispositivos/capacidades"
---

# Como ver as capacidades por modelo

**Objetivo:** saber, por modelo e firmware, o que está comprovado (coleta, leitura, reiniciar, Wi-Fi, ONU na OLT).

**Antes de começar:** permissão `inventory:read`. Somente leitura.

## Passo a passo

1. Acesse **Rede** e abra a aba **Capacidades**.
2. Cada linha é um perfil (fabricante, modelo, firmware) do seu inventário; cada coluna, uma operação.
3. Leia a célula: **Suportada / Não suportada / Desconhecida**, o nível (**Identificado**, **Observado**, **Certificado**) e se é leitura ou escrita.

## Como ler

- **Desconhecida** é a ausência de evidência: nunca é suporte.
- **Bloqueada: não homologada** em uma escrita: a operação não roda nesse perfil, exceto no alvo de bancada homologado.
- **Observado** vem de execução real supervisionada; **Certificado** só por homologação formal.
