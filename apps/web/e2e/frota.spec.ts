import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { login } from "./helpers";

// Frota de OLTs (ADR-0041, PR2 parte A): cadastro e edição na nuvem. Nada é enviado à OLT e a credencial é só um NOME (nunca repetido na tela).
const SUFFIX = String(Date.now()).slice(-6);

test("frota: cria POP, cadastra OLT, edita POP/rótulo/credencial, sem a tela repetir o nome da credencial recusada", async ({ page }) => {
  await login(page);
  await page.goto("/rede");
  await page.getByTestId("rede-frota-link").click();
  await expect(page).toHaveURL(/\/rede\/frota$/);
  await expect(page.getByTestId("frota-cadastro")).toContainText("Nunca digite senha, community ou chave aqui");
  // POP
  await page.getByTestId("frota-pops").getByLabel("Nome do POP").fill(`POP E2E ${SUFFIX}`);
  await page.getByTestId("frota-pops").getByLabel("Código (opcional)").fill(`E2E-${SUFFIX}`);
  await page.getByTestId("frota-criar-pop").click();
  await expect(page.getByTestId("frota-flash")).toContainText("POP criado");
  await expect(page.getByTestId("frota-pop").filter({ hasText: `POP E2E ${SUFFIX}` })).toHaveCount(1);
  // uma credencial que é um ENDEREÇO é recusada e o valor não volta na tela
  const form = page.getByTestId("frota-cadastro");
  await form.getByLabel("Nome da OLT").fill(`E2E-OLT-${SUFFIX}`);
  await form.getByLabel("Nome da credencial no Edge (opcional)").fill("10.9.8.7");
  await page.getByTestId("frota-cadastrar").click();
  await expect(page.getByTestId("frota-flash")).toContainText("fora do formato");
  await expect(page.locator("body")).not.toContainText("10.9.8.7");
  // cadastro válido
  await form.getByLabel("Nome da OLT").fill(`E2E-OLT-${SUFFIX}`);
  await form.getByLabel("Site / POP").fill(`POP E2E ${SUFFIX}`.slice(0, 12));   // busca parcial: escolher o site existente da lista
  await form.getByTestId("pop-opcao").filter({ hasText: `POP E2E ${SUFFIX}` }).click();
  await expect(form.getByTestId("pop-estado")).toContainText("Site existente");
  await form.getByLabel("Rótulo (opcional)").fill("OLT de teste");
  await form.getByLabel("Nome da credencial no Edge (opcional)").fill(`olt-e2e-${SUFFIX}`);
  await page.getByTestId("frota-cadastrar").click();
  await expect(page.getByTestId("frota-flash")).toContainText("OLT cadastrada");
  const card = page.getByTestId("frota-olt").filter({ hasText: `E2E-OLT-${SUFFIX}` });
  await expect(card).toHaveCount(1);
  await expect(card).toContainText("Ainda não coletada");
  await expect(card).toContainText(`POP E2E ${SUFFIX}`);
  await expect(card).toContainText("credencial configurada");
  // o mesmo nome de novo é recusado
  await form.getByLabel("Nome da OLT").fill(`E2E-OLT-${SUFFIX}`);
  await page.getByTestId("frota-cadastrar").click();
  await expect(page.getByTestId("frota-flash")).toContainText("Já existe");
  // detalhe e edição
  await card.getByRole("link", { name: `E2E-OLT-${SUFFIX}` }).click();
  await expect(page.getByTestId("frota-detalhe")).toContainText("ainda não lido pelo Edge");
  await expect(page.getByTestId("frota-credencial")).toContainText("Informada");
  await expect(page.getByLabel("Substituir o nome da credencial no Edge")).toHaveValue("");               // o nome nunca volta da API
  await expect(page.locator("body")).not.toContainText(`olt-e2e-${SUFFIX}`);
  await page.getByLabel("Rótulo").fill("Rótulo novo");
  await page.getByTestId("frota-salvar").click();                                                         // sem tocar na credencial: ela continua informada
  await expect(page.getByTestId("frota-flash")).toContainText("OLT atualizada");
  await expect(page.getByLabel("Rótulo")).toHaveValue("Rótulo novo");
  await expect(page.getByTestId("frota-credencial")).toContainText("Informada");
  await page.getByLabel("Remover o nome da credencial").check();
  await page.getByTestId("frota-salvar").click();
  await expect(page.getByTestId("frota-credencial")).toContainText("Não informada");
  const res = await new AxeBuilder({ page: page as never }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  expect(res.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => v.id)).toEqual([]);
});

test("frota: parâmetros repetidos na URL e página inexistente não derrubam a tela", async ({ page }) => {
  await login(page);
  for (const qs of ["?ok=olt&ok=pop", "?erro=nome&erro=falha", "?ok[]=x&erro[a]=1", "?ok=%00"]) {
    const r = await page.goto(`/rede/frota${qs}`);
    expect(r?.status(), qs).toBe(200);
  }
  expect((await page.goto("/rede/frota/00000000-0000-0000-0000-000000000000"))?.status()).toBe(404);
  expect((await page.goto("/rede/frota/nao-e-uuid"))?.status()).toBe(404);
});

test("frota: teste de conexão pede a leitura ao Edge, mostra 'aguardando' e bloqueia o segundo pelo orçamento de 15 minutos", async ({ page }) => {
  await login(page);
  await page.goto("/rede/frota");
  // uma OLT do demo (cadastrada pelo Edge de demonstração); o teste só PEDE a leitura: nada é enviado daqui
  const first = page.getByTestId("frota-olt").filter({ hasNotText: "E2E-" }).first();   // as OLTs "E2E-*" são criadas por outros testes deste arquivo (alguns já gastam o orçamento)
  await first.getByRole("link").first().click();
  const box = page.getByTestId("frota-teste");
  await expect(box).toContainText("somente leitura");
  await expect(box).toContainText("1 teste a cada 15 minutos e 4 por hora");
  await expect(page.getByTestId("frota-sem-identidade")).toBeVisible();
  await page.getByTestId("frota-testar").click();
  await expect(page.getByTestId("frota-flash")).toContainText("Teste pedido ao Edge");
  await expect(page.getByTestId("frota-testes")).toContainText("Aguardando o Edge");
  await expect(page.getByTestId("frota-orcamento")).toContainText("1 de 4 na última hora");
  await expect(page.getByTestId("frota-orcamento")).toContainText("Próximo teste em cerca de");
  await expect(page.getByTestId("frota-testar")).toBeDisabled();                        // o orçamento de 15 minutos desliga o botão
  const res2 = await new AxeBuilder({ page: page as never }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  expect(res2.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" || ")}`)).toEqual([]);
});

test("frota: site digitado que não existe é oferecido para criar e nasce junto com a OLT; endereço fica mascarado; cadastrar e testar", async ({ page }) => {
  await login(page);
  await page.goto("/rede/frota");
  const form = page.getByTestId("frota-cadastro");
  const novo = `Site Novo ${SUFFIX}`;
  await form.getByLabel("Nome da OLT").fill(`E2E-NEW-${SUFFIX}`);
  await form.getByLabel("Site / POP").fill(novo);
  await expect(form.getByTestId("pop-adicionar")).toContainText(`Adicionar “${novo}” como novo site`);
  await form.getByTestId("pop-adicionar").click();
  await expect(form.getByTestId("pop-estado")).toContainText("será criado ao salvar");
  await form.getByLabel("Endereço de gerência (opcional)").fill("10.77.88.99");
  await form.getByLabel("Versão do SNMP (opcional)").selectOption("v2c");
  await page.getByTestId("frota-cadastrar-testar").click();
  // cadastra e vai para o detalhe com o teste pedido (ou, sem canal do Edge no ambiente, com o aviso de que o teste não pôde ser pedido): em ambos o cadastro existe
  await expect(page).toHaveURL(new RegExp(`/rede/frota/[0-9a-f-]{36}`));
  await expect(page.getByTestId("frota-flash")).toContainText("OLT cadastrada");
  await expect(page.getByTestId("frota-endereco")).toContainText("10.77.•.•");
  await expect(page.getByTestId("frota-endereco")).toContainText("SNMP v2c");
  await expect(page.locator("body")).not.toContainText("10.77.88.99");
  await expect(page.getByLabel("Site / POP")).toHaveValue(novo);
  const axeDetalhe = await new AxeBuilder({ page: page as never }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  expect(axeDetalhe.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => v.id)).toEqual([]);
  // o site foi criado uma vez só
  await page.goto("/rede/frota");
  await expect(page.getByTestId("frota-pop").filter({ hasText: novo })).toHaveCount(1);
  // a lista aberta (com a opção de criar) também passa no axe
  await form.getByLabel("Site / POP").fill(`Outro Site ${SUFFIX}`);
  await expect(form.getByTestId("pop-adicionar")).toBeVisible();
  const axeLista = await new AxeBuilder({ page: page as never }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  expect(axeLista.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ") + " | " + n.failureSummary?.slice(0, 160)).join(" || ")}`)).toEqual([]);
  await form.getByLabel("Site / POP").fill("");
  // um endereço inválido é recusado sem ser repetido na tela
  await form.getByLabel("Nome da OLT").fill(`E2E-BAD-${SUFFIX}`);
  await form.getByLabel("Endereço de gerência (opcional)").fill("olt.exemplo.com");
  await page.getByTestId("frota-cadastrar").click();
  await expect(page.getByTestId("frota-flash")).toContainText("fora do formato");
  await expect(page.locator("body")).not.toContainText("olt.exemplo.com");
});
