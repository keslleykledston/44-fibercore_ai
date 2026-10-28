/**
 * EXEMPLO CONCEITUAL para migrar para help-screenshots.spec.ts
 * SOMENTE após apps/web + rotas + seed sintética implementados.
 * Não trate isto como teste já executado.
 */
import { test, expect } from '@playwright/test';

const cases = [
  { name: 'desktop', width: 1440, height: 900 },
  { name: 'mobile', width: 390, height: 844 },
];

for (const viewport of cases) {
  test(`manual consultar ONU - ${viewport.name}`, async ({ page }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    // Preparar sessão autenticada de tenant MOCK e fixture sintética (não produção).
    // Implementar setup de auth em playwright fixtures após backend real.
    await page.goto('/rede/onus');
    await expect(page.getByTestId('onu-inventory-ready')).toBeVisible();
    await page.screenshot({
      path: `docs/help/assets/rede/consultar-onu/${viewport.name}.png`,
      fullPage: true,
      animations: 'disabled',
    });
  });
}
