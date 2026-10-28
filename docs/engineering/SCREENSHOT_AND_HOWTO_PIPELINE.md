# Pipeline obrigatório — Screenshots e How-to a cada evolução de UX

**Regra de merge:** nenhuma alteração funcional de tela está completa sem atualização do manual respectivo, screenshots reais desktop/mobile e teste E2E ligado ao commit. Exceção: scaffolds de protótipos marcados `draft` e não expostos em produção.

## Padrão de arquivos

```text
apps/web/e2e/help-screenshots.spec.ts
apps/web/src/... (UI integrada)
docs/help/screenshot-manifest.yaml
docs/help/how-to/<categoria>/<slug>.md
docs/help/assets/<categoria>/<slug>/desktop.png
docs/help/assets/<categoria>/<slug>/mobile.png
docs/help/assets/<categoria>/<slug>/error.png (quando relevante)
```

## Captura automatizada com Playwright

1. Subir stack teste e `web` com ambiente isolado; login via usuários de seed sem privilégios reais.
2. Fixar locale `pt-BR`, timezone `America/Manaus`, relógio de fixture e dados estáveis; mascarar PII. Usar `data-testid` estáveis, não CSS frágil.
3. Executar Chromium Playwright com viewport `1440x900` e `390x844`, `animations: disabled`, aguardar sinal de UI pronta e fontes; não usar timeouts arbitrários como critério de estabilidade.
4. Capturar screenshots **da aplicação integrada** (nunca substituir captura por desenho de Lovable); incluir `loading`, `stale`, `empty`, `error`, `403` e `pending approval` quando a tela os oferecer.
5. Referenciar imagem no artigo de ajuda usando caminho relativo e texto alternativo; usar legendas curtas, evitando setas desenhadas sobre dados pessoais.
6. Rodar testes, `python tests/validate_help.py`, revisão visual manual e Codex; registrar SHA, versão, data, URL local de teste e evidências.
7. Publicar artigo `published` só depois do aceite e screenshots presentes, rastreáveis e atuais.

Consulte `apps/web/e2e/help-screenshots.spec.example.ts` para um **exemplo não executável até a implementação do frontend**. Adicionar o `HelpContextLink` na tela de origem e validar `/ajuda/<slug>` com deep link.

## Política de atualização

PR mudou estrutura, nome de botão, localização, resultado ou estados? **Regenerar screenshot, revisar o texto e alterar `last_verified` no mesmo PR**. Falhas de teste, screenshots artificiais, conteúdo sensível, caminhos quebrados ou tutorial divergente são `BLOCK` no Codex.

## Segurança de publicação

Ajuda do produto não contém IPs reais, identificadores de clientes, segredos de API, dumps TR-069/USP nem rotas administrativas internas. A documentação de arquitetura continua restrita à equipe de engenharia.
