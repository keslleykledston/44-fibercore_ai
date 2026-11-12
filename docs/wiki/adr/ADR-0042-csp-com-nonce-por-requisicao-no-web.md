# ADR-0042: CSP com nonce por requisição no web (Next.js)

Status: Accepted (modo padrão `report-only`; `enforce` por variável) | Data: 2026-11-11 | Owner: equipe
Complementa ADR-0014 (BFF/cookie) e ADR-0016 (nginx do host). Fecha a pendência "CSP sem `unsafe-inline` (nonce)" do lado do app.

## Contexto
- Hoje o único CSP vem do nginx do HOST (`infra/deploy/nginx/*.conf`): `script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'`. Com `'unsafe-inline'` em `script-src` a CSP não barra XSS por injeção de HTML. O nginx esconde o CSP do upstream (`proxy_hide_header Content-Security-Policy`).
- O Next 15 emite scripts inline próprios (flight data, `$RC` do Suspense, bootstrap) e o app tem UM script inline (tema, `layout.tsx`). Nonce estático não serve: tem de ser novo por requisição, e por isso tem de nascer no Next (nginx não consegue).
- Estilo: o CSS vem de `/_next/static/css/*.css` (`<link>`); não há `<style>` de elemento. Há 14 pontos de atributos `style={{…}}` dinâmicos em 3 componentes (`OpticalRuler`, `Faceplate`, `OltPanel`: posição % na régua, cor de LED, posição do popover).

## Opções
A. Manter o CSP do host e só trocar `'unsafe-inline'` por hashes: inviável (scripts do Next mudam a cada requisição/build).
B. Middleware do Next com nonce + `'strict-dynamic'` (decidido).
C. Eliminar todos os atributos `style` para fechar também `style-src-attr`: ganho pequeno (CSS não executa script), custo/risco visual alto na régua óptica (já coberta por testes de contraste). Fica como melhoria futura.

## Decisão
1. `src/middleware.ts` gera um nonce de 128 bits por requisição (`src/lib/csp.ts`, funções puras) e o coloca (a) no cabeçalho de REQUISIÇÃO `Content-Security-Policy[-Report-Only]` (é de lá que o Next extrai o nonce e o aplica aos próprios scripts), (b) em `x-nonce` (o `layout.tsx` o aplica ao script do tema), (c) no cabeçalho de RESPOSTA. Cabeçalhos de política vindos do cliente são descartados.
2. Política:
   `default-src 'self'; script-src 'self' 'nonce-N' 'strict-dynamic'; style-src 'self' 'nonce-N'; style-src-attr 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'`.
   - Script: sem `'unsafe-inline'` e sem `'unsafe-eval'` em produção (dev acrescenta `'unsafe-eval'` e `ws:` para o HMR do Next). `'self'` fica só de reserva para navegador sem CSP3.
   - `img-src data:` = QR do MFA (`QRCode.toDataURL`); sem `blob:`, sem `https:`. `connect-src 'self'`: o navegador só fala com o próprio origin (BFF).
3. **O que sobra de `'unsafe-inline'`: UM item, `style-src-attr`.** Nonce não vale para atributo `style=""`, e os 14 pontos de atributo são renderizados no servidor. `style-src` (elementos `<style>`/`<link>`) NÃO tem `'unsafe-inline'`. Risco residual: só CSS injetado por atributo (sem execução de script). Navegador sem `style-src-attr` (Safari < 15.4, Firefox < 105) cai para `style-src` e perde esses estilos (degradação visual, não de segurança). Caminho para zerar: trocar os 14 pontos de atributo por classes/variáveis CSS e remover a diretiva (o teste unitário "o ÚNICO unsafe-inline" passa a exigir lista vazia). Um atributo estático foi eliminado agora (`cursor`/`outline` do `fc-pon` viraram classes).
4. Modo por `FIBERCORE_CSP_MODE` (lido a cada requisição, sem rebuild): `report-only` (PADRÃO; emite `Content-Security-Policy-Report-Only`), `enforce` (emite `Content-Security-Policy`), `off` (nada). Valor ausente ou desconhecido = `report-only`. `FIBERCORE_CSP_REPORT_URI` (opcional; caminho absoluto ou `https://` simples, validado) acrescenta `report-uri`; sem ele as violações só aparecem no console do navegador. O repo não traz coletor: um endpoint público sem autenticação seria superfície de spam.
5. O middleware agora também cobre `/login` e `/login/mfa` (antes excluídos do matcher); a renovação de sessão continua não rodando ali. `/_next/`, `/bff/` (JSON/redirecionamentos), `/ajuda-assets/` e favicon seguem fora.
6. Implicação de cache: o layout lê `headers()`, então TODAS as páginas são renderizadas por requisição (`ƒ Dynamic`), sem HTML estático/ISR. Quase todas já eram dinâmicas (cookies de sessão); `/login`, `/login/mfa` e a 404 passam a ser. `Cache-Control` do HTML continua `private, no-cache, no-store`. Os ativos de `/_next/static` seguem imutáveis e cacheáveis. Nenhum CDN/cache de HTML pode ficar na frente (o nonce é por resposta; HTML cacheado reutilizaria nonce e quebraria os scripts).
7. `'strict-dynamic'`: script criado por DOM a partir de código já confiável é permitido por desenho (é assim que o Next carrega chunks). A defesa é impedir que o atacante execute o primeiro script: script inserido pelo parser sem nonce, `onclick=`/`onerror=` inline, `javascript:` e `eval` são barrados (provado em e2e).

## O que o dono do host precisa mudar (fora do escopo do repo; exige root)
Ver `docs/operations/CSP_HOST_NGINX.md`. Resumo: enquanto o nginx esconder o CSP do upstream e impuser o próprio, `enforce` no app não tem efeito. Em `report-only` (padrão) NÃO é preciso mudar nada: o nginx só esconde o cabeçalho de nome `Content-Security-Policy`; o `-Report-Only` passa e permite validar a política real no navegador sem risco.

## Consequências
- Testes: unitário `e2e/csp-pure.spec.ts` (projeto `puros`, 6 casos); `e2e/csp.spec.ts` (projeto `csp`): 21 páginas + ONU 360 + diagnóstico + navegação RSC sem violação em report-only E em enforce, nonce diferente a cada requisição, todo `<script>` com o nonce da resposta, nenhum `<style>`, e provas de bloqueio em enforce (script sem nonce injetado no HTML, `onerror`/`onclick`, `javascript:`, `<style>` sem nonce, `eval`), mais a prova do restante (`style=` segue valendo). Rodar enforce: segunda instância `next start` com `FIBERCORE_CSP_MODE=enforce` e `CSP_ENFORCE_URL`.
- Rollback: `FIBERCORE_CSP_MODE=report-only` (ou `off`) e recriar o contêiner `web`; sem rebuild, sem migração.
- Ordem de adoção sugerida: (1) deploy com padrão `report-only`; (2) navegar a LAB real com o console aberto e confirmar zero violações; (3) dono do host aplica a mudança do nginx; (4) `FIBERCORE_CSP_MODE=enforce`; (5) conferir com `curl -sI`.
- Risco conhecido: extensões de navegador que injetam script/estilo geram ruído no console em report-only (não é do app).
- Não coberto: relatório centralizado de violações (sem coletor); migração para `report-to`/Reporting API.
