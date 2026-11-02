/**
 * Capturas REAIS da aplicação integrada (Next.js + API + Postgres) com seed sintético (scripts/seed_demo.py).
 * Gera docs/help/assets/<categoria>/<slug>/{desktop,mobile}.png. Dados de tempo relativo ficam mascarados.
 */
import path from "node:path";
import { expect, type APIRequestContext, type Page, test } from "@playwright/test";
import { API_URL, EMAIL, login, PASSWORD } from "./helpers";

const ROOT = path.resolve(__dirname, "..", "..", "..", "docs", "help", "assets");
/** Gera as SUGESTÕES ONU↔CPE (idempotente) para a captura mostrar o card do roteador com o pedido de confirmação humana. */
const suggestLinks = async (request: APIRequest) => {
  const tok = (await (await request.post(`${API_URL}/v1/auth/token`, { data: { email: EMAIL, password: PASSWORD } })).json()).access_token as string;
  expect((await request.post(`${API_URL}/v1/onu-cpe-links/suggest`, { headers: { Authorization: `Bearer ${tok}` } })).status()).toBe(201);
};
/** Cliente demo SEM ONU aprovada pelos outros testes: aprova o vínculo (idempotente) e devolve a rota da Visão 360. */
const sub360Route = async (request: APIRequest) => {
  const tok = (await (await request.post(`${API_URL}/v1/auth/token`, { data: { email: EMAIL, password: PASSWORD } })).json()).access_token as string;
  const h = { Authorization: `Bearer ${tok}` };
  const assoc = (await (await request.get(`${API_URL}/v1/associations?status=suggested&limit=200`, { headers: h })).json()) as { id: string; customer_name: string }[];
  const a = assoc.find((x) => x.customer_name === "Cliente Demo Três");
  if (a) expect((await request.post(`${API_URL}/v1/associations/${a.id}/approve`, { headers: h })).status()).toBe(200);
  const cu = (await (await request.get(`${API_URL}/v1/customers?limit=200`, { headers: h })).json()) as { id: string; display_name: string }[];
  return `/assinantes/${cu.find((x) => x.display_name === "Cliente Demo Três")!.id}`;
};
/** Cliente demo numa PON com queda coletiva: aprova o vínculo, executa o diagnóstico (somente leitura) e devolve a rota já com o resultado. */
const diagRoute = async (request: APIRequest) => {
  const tok = (await (await request.post(`${API_URL}/v1/auth/token`, { data: { email: EMAIL, password: PASSWORD } })).json()).access_token as string;
  const h = { Authorization: `Bearer ${tok}` };
  const assoc = (await (await request.get(`${API_URL}/v1/associations?status=suggested&limit=200`, { headers: h })).json()) as { id: string; customer_name: string }[];
  const a = assoc.find((x) => x.customer_name === "Cliente Demo Cinco");
  if (a) expect((await request.post(`${API_URL}/v1/associations/${a.id}/approve`, { headers: h })).status()).toBe(200);
  const cu = (await (await request.get(`${API_URL}/v1/customers?limit=200&q=Demo%20Cinco`, { headers: h })).json()) as { id: string }[];
  const ctx = (await (await request.get(`${API_URL}/v1/customers/${cu[0].id}/context`, { headers: h })).json()) as { onus: { id: string }[] };
  const run = (await (await request.post(`${API_URL}/v1/diagnostics/runs`, { headers: h, data: { rule_id: "R-D001", onu_id: ctx.onus[0].id } })).json()) as { run_id: string };
  return `/assinantes/diagnostico/${cu[0].id}?onu=${ctx.onus[0].id}&run=${run.run_id}`;
};
/** Aprova o vínculo do Cliente Demo Cinco (ONU numa PON em queda) para a captura do NOC mostrar o impacto. */
const approveCinco = async (request: APIRequest) => {
  const tok = (await (await request.post(`${API_URL}/v1/auth/token`, { data: { email: EMAIL, password: PASSWORD } })).json()).access_token as string;
  const h = { Authorization: `Bearer ${tok}` };
  const assoc = (await (await request.get(`${API_URL}/v1/associations?status=suggested&limit=200`, { headers: h })).json()) as { id: string; customer_name: string }[];
  const a = assoc.find((x) => x.customer_name === "Cliente Demo Cinco");
  if (a) expect((await request.post(`${API_URL}/v1/associations/${a.id}/approve`, { headers: h })).status()).toBe(200);
};
/** Rascunho SINTÉTICO do Profile Studio já comparado e simulado (via API, sem OLT): devolve a rota com a comparação e o resultado da simulação. */
const painelRoute = async (request: APIRequestContext) => {
  const tok = (await (await request.post(`${API_URL}/v1/auth/token`, { data: { email: EMAIL, password: PASSWORD } })).json()).access_token as string;
  const olt = ((await (await request.get(`${API_URL}/v1/olts?limit=200`, { headers: { Authorization: `Bearer ${tok}` } })).json()) as { id: string; name: string }[]).find((o) => o.name === "OLT-DEMO-PAINEL")!;
  return `/rede?olt=${olt.id}`;
};
const frotaTesteRoute = async (request: APIRequestContext) => {
  const tok = (await (await request.post(`${API_URL}/v1/auth/token`, { data: { email: EMAIL, password: PASSWORD } })).json()).access_token as string;
  const olt = ((await (await request.get(`${API_URL}/v1/fleet/olts`, { headers: { Authorization: `Bearer ${tok}` } })).json()) as { items: { id: string; name: string }[] }).items.find((o) => o.name === "OLT-DEMO-02")!;
  return `/rede/frota/${olt.id}`;
};
const perfisRoute = async (request: APIRequestContext) => {
  const tok = (await (await request.post(`${API_URL}/v1/auth/token`, { data: { email: EMAIL, password: PASSWORD } })).json()).access_token as string;
  const h = { Authorization: `Bearer ${tok}` };
  const olt = ((await (await request.get(`${API_URL}/v1/olts?limit=200`, { headers: h })).json()) as { id: string; name: string }[]).find((o) => o.name === "OLT-DEMO-01")!;
  const snap = ((await (await request.get(`${API_URL}/v1/olts/${olt.id}/profiles`, { headers: h })).json()) as { items: { id: string; native_key: string }[] }).items.find((i) => i.native_key === "DEMO-LINHA-500M")!;
  const d = (await (await request.post(`${API_URL}/v1/profile-drafts`, { headers: h, data: { name: "Linha 500M com mais banda (exemplo)", reason: "exemplo da ajuda", source_snapshot_id: snap.id, target_olt_ids: [olt.id], desired: { dba_type: "type4", maximum_kbps: 750000, customer_vlan: 100, tagging: "tagged", shaping_owner: "olt" } } })).json()) as { id: string };
  const run = (await (await request.post(`${API_URL}/v1/profile-drafts/${d.id}/dry-run`, { headers: h, data: {} })).json()) as { run_id: string };
  return `/rede/perfis/${d.id}?comparar=${snap.id}&run=${run.run_id}`;
};
type APIRequest = APIRequestContext;
const screens: { slug: string; route: string; ready: string; prepare?: (r: APIRequest) => Promise<void>; dynamicRoute?: (r: APIRequest) => Promise<string>; steps?: (page: Page) => Promise<void> }[] = [
  { slug: "visao-geral/visao-geral", route: "/", ready: "kpis" },
  { slug: "rede/consultar-onu", route: "/rede", ready: "onu-inventory-ready" },
  { slug: "rede/onu-360", route: "/rede?serial=DEMOA0001", ready: "onu360-ready", prepare: suggestLinks,
    steps: async (page: Page) => { await page.getByTestId("onu-open").click(); await page.getByTestId("onu-360-link").click(); } },
  { slug: "rede/perfis-olt", route: "/rede/perfis", ready: "perfis-inventario" },
  { slug: "rede/perfis-olt/rascunho", route: "/rede/perfis", ready: "perfis-resultado", dynamicRoute: perfisRoute },
  { slug: "rede/painel-da-olt", route: "/rede", ready: "olt-popover", dynamicRoute: painelRoute,
    steps: async (page: Page) => { await page.locator('[data-testid="olt-pon"][data-port-key="0/0/1"]').click(); await expect(page.getByTestId("olt-popover")).toBeVisible(); } },
  { slug: "rede/frota-de-olts", route: "/rede/frota", ready: "frota-lista" },
  { slug: "rede/frota-de-olts/teste", route: "/rede/frota", ready: "frota-testes", dynamicRoute: frotaTesteRoute,
    steps: async (page: Page) => {   // a captura desktop já gastou o pedido (o orçamento desliga o botão): a mobile só confere o resultado
      const b = page.getByTestId("frota-testar");
      if (await b.isEnabled()) await b.click();
      await expect(page.getByTestId("frota-testes")).toContainText("Aguardando o Edge");
    } },
  { slug: "rede/catalogo-de-equipamentos", route: "/rede/catalogo", ready: "catalogo-grade",
    steps: async (page: Page) => {   // as miniaturas são lazy: a captura só vale com todas carregadas
      await page.evaluate(async () => { for (const i of Array.from(document.images)) i.loading = "eager"; await Promise.all(Array.from(document.images).map((i) => (i.complete ? 0 : new Promise((r) => { i.onload = i.onerror = r; })))); });
    } },
  { slug: "rede/base-de-conhecimento", route: "/rede/conhecimento?secao=comandos", ready: "kb-comandos" },
  { slug: "rede/onus-pendentes", route: "/rede/pendentes", ready: "pend-fila" },
  { slug: "assinantes/visao-360", route: "/assinantes", ready: "sub360-ready", dynamicRoute: sub360Route },
  { slug: "assinantes/diagnostico-guiado", route: "/assinantes", ready: "diag-ready", dynamicRoute: diagRoute },
  { slug: "noc/acompanhar-incidente", route: "/noc", ready: "incident-queue", prepare: approveCinco,
    steps: async (page: Page) => { await page.getByTestId("incident-open").first().click(); await expect(page.getByTestId("incident-detail")).toBeVisible(); } },
  { slug: "assinantes/importar-e-revisar-vinculos", route: "/assinantes", ready: "association-list" },
  { slug: "operacoes/acompanhar-operacoes", route: "/operacoes", ready: "jobs-table" },
  { slug: "administracao/saude-modulos", route: "/administracao/modulos", ready: "modules-table" },
  { slug: "administracao/membros-e-mfa", route: "/administracao/equipe", ready: "team-ready" },
  { slug: "conta/ativar-verificacao-em-duas-etapas", route: "/conta/seguranca", ready: "security-page" },
  { slug: "ajuda/central-de-ajuda", route: "/ajuda", ready: "help-list" },
];
const viewports = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "mobile", width: 390, height: 844 },
];

for (const vp of viewports) {
  test.describe(`capturas ${vp.name}`, () => {
    test.use({ viewport: { width: vp.width, height: vp.height }, deviceScaleFactor: 1 });
    for (const s of screens) {
      test(`${s.slug} - ${vp.name}`, async ({ page, request }) => {
        await s.prepare?.(request);
        await login(page);
        await page.goto(s.dynamicRoute ? await s.dynamicRoute(request) : s.route);
        await s.steps?.(page);
        await expect(page.getByTestId(s.ready)).toBeVisible();
        await page.evaluate(() => document.fonts.ready);
        await page.screenshot({
          path: path.join(ROOT, s.slug, `${vp.name}.png`),
          fullPage: true,
          animations: "disabled",
          mask: [page.getByTestId("freshness"), page.getByTestId("volatile")],
          maskColor: "#C9D1DA",
        });
      });
    }
  });
}
