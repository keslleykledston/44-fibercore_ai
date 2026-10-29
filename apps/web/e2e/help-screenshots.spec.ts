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
type APIRequest = APIRequestContext;
const screens: { slug: string; route: string; ready: string; prepare?: (r: APIRequest) => Promise<void>; dynamicRoute?: (r: APIRequest) => Promise<string>; steps?: (page: Page) => Promise<void> }[] = [
  { slug: "visao-geral/visao-geral", route: "/", ready: "kpis" },
  { slug: "rede/consultar-onu", route: "/rede", ready: "onu-inventory-ready" },
  { slug: "rede/onu-360", route: "/rede?serial=DEMOA0001", ready: "onu360-ready", prepare: suggestLinks,
    steps: async (page: Page) => { await page.getByTestId("onu-open").click(); await page.getByTestId("onu-360-link").click(); } },
  { slug: "assinantes/visao-360", route: "/assinantes", ready: "sub360-ready", dynamicRoute: sub360Route },
  { slug: "noc/acompanhar-incidente", route: "/noc", ready: "incident-queue" },
  { slug: "assinantes/importar-e-revisar-vinculos", route: "/assinantes", ready: "association-list" },
  { slug: "operacoes/acompanhar-operacoes", route: "/operacoes", ready: "jobs-table" },
  { slug: "administracao/saude-modulos", route: "/administracao/modulos", ready: "modules-table" },
  { slug: "administracao/membros-e-mfa", route: "/administracao/membros", ready: "members-table" },
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
