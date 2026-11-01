# Handoff de UX para o Lovable — Ambiente "Diagnóstico" da ONU + régua de sinal óptico

Projeto Lovable de referência: `13aaf09e-023f-464e-8651-190d6d928dfc`. **Só proposta visual** (protótipo com dados SINTÉTICOS). Nada do código do Lovable entra no repositório; o produto é Next.js + Tailwind com tokens próprios e reproduz o padrão. Sem segredos, endereços de equipamento ou dados de cliente neste documento.

## 1. O que pedimos (um lote)
1. **Tela "Diagnóstico da ONU"** (rota de uma ONU), reunindo os testes que o operador faz numa ONU: **sinal óptico**, **velocidade** (download e upload), **qualidade da conexão** (leitura rápida) e **latência / jitter / ping / DNS**.
2. **Régua de sinal óptico** com gradiente de cor, no lugar do número solto "-13,04 dBm", em três tamanhos: grande (tela de Diagnóstico), média (painel lateral da ONU) e compacta (linha de tabela, só marcador + rótulo).

## 2. Régua de sinal óptico — especificação
- Eixo horizontal em dBm, de **−34 (esquerda) a −3 (direita)**. Marcador (triângulo) na posição do valor lido, com o número ao lado ou acima (ex.: "−14,66 dBm").
- Faixas de **referência** (padrão ITU-T G.984.2, classe B+, receptor da ONU: sensibilidade −28 dBm, sobrecarga −8 dBm):

| Faixa | Intervalo (dBm) | Rótulo | Cor (token) |
|---|---|---|---|
| Crítico (fraco) | abaixo de −28 | "Crítico · sinal fraco" | perigo |
| Atenção (fraco) | −28 até abaixo de −25 | "Atenção · margem baixa" | aviso |
| Bom | −25 até −10 | "Bom" | ok |
| Atenção (forte) | acima de −10 até −8 | "Atenção · sinal forte" | aviso |
| Crítico (forte) | acima de −8 | "Crítico · sobrecarga" | perigo |

- O fundo da régua é um **gradiente suave** perigo → aviso → ok → aviso → perigo, alinhado a essas faixas. Marcas de escala em **−28, −25, −10 e −8** com o valor escrito.
- **Cor nunca é o único indicador:** sempre rótulo em texto + símbolo (✓ bom, ! atenção, ✕ crítico) ao lado do marcador, e `aria-label` completo ("Nível óptico −14,66 dBm: bom. Referência G.984.2 classe B+").
- **Aviso fixo e discreto** perto da régua: "Faixa de referência do padrão (G.984.2 classe B+). Não homologada para esta OLT/óptica."
- Estados: **normal** (cada faixa), **sem leitura** (sem marcador; "Sem leitura de sinal"), **dado defasado** (marcador vazado/translúcido + "Último valor conhecido · há 2 h", sem afirmar que o sinal atual é bom), **carregando** e **erro**.
- Contraste mínimo WCAG AA em tema claro e escuro; foco visível; funciona a 360 px de largura e com `prefers-reduced-motion` (sem animar o marcador).

## 3. Tela "Diagnóstico da ONU" — estrutura
- **Topo:** título "Diagnóstico", serial sintético (ex.: `DEMOA0001`), local (OLT › PON), estado (online/fora do ar) e "Atualizado · há N min". Botão "← Voltar para a ONU".
- **Bloco "Sinal óptico"** com a régua grande, Rx em dBm, frescor do dado e fonte ("Leitura da OLT").
- **Abas** (links, nada de rótulo só por ícone): **Resumo · Velocidade · Qualidade · Latência e DNS**.
  - **Resumo:** uma grade de cartões, um por teste, cada um com **estado de disponibilidade em texto**: "Disponível", "Indisponível: sem roteador vinculado", "Indisponível: recurso desligado para este provedor", "Em homologação". Cada cartão leva à sua aba.
  - **Velocidade:** escolha do sentido (download / upload), tamanho do arquivo (10 MB, 50 MB, 200 MB), botão "Pedir teste" (pede e outra pessoa aprova), histórico curto com vazão em Mbps, duração e o motivo quando for **parcial** ("medição curta demais: não representa a capacidade da linha"). Texto fixo: "Mede a WAN de serviço (PPPoE) da ONT, o que o provedor entrega ao cliente. Não mede Wi-Fi nem rede interna."
  - **Qualidade:** leitura rápida com sinais (óptica, WAN, Wi-Fi) em texto + símbolo, rótulos de confiança Confirmado / Hipótese / Indisponível.
  - **Latência e DNS:** **Em homologação.** Mostrar o desenho já pronto, desabilitado e honesto: ping (latência mínima/média/máxima e perda), jitter (variação da latência), DNS (tempo de resolução) e "para a internet". Nenhum número inventado: cada cartão mostra "Ainda não disponível" e o motivo ("exige a homologação por modelo de aparelho").
- **Nada inicia sozinho.** Cada teste gera tráfego e é pedido por uma pessoa com permissão; o texto deve dizer isso.

## 4. Regras do produto que o protótipo deve respeitar
- Português do Brasil com acentuação correta. Linguagem de operação, curta.
- Estado nunca só por cor (rótulo + símbolo). Sem seletor de estado "DEMO" no produto final (pode existir só no protótipo).
- Sem botão de escrita na rede. Sem "saída bruta" de equipamento. Sem endereço IP de equipamento na tela.
- ACS sem contato **não** é ONU offline; dado velho é "sem leitura/defasado", nunca "fora".
- Densidade e hierarquia de painel de operação (cartões, tipografia numérica tabular), tema claro/escuro por tokens; **não** copiar paleta de produto de terceiros.

## 5. Entrega esperada
Uma página de demonstração com a tela completa e a régua nos três tamanhos, com um seletor de estados **só para o protótipo** (normal por faixa, sem leitura, defasado, carregando, erro; teste disponível/indisponível/em homologação), em tema claro e escuro, desktop e 360 px. Uma nota curta dizendo o que **não** foi verificado (contraste real, tema escuro, estados).
