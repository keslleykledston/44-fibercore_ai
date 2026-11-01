import { expect, test } from "@playwright/test";
import { mix } from "../src/lib/contrast";

// A composição que o guarda de contraste usa (`mix`) tem de ser a MESMA que o navegador faz com `color-mix(in srgb, …)`: aqui o resultado calculado no Chromium real é comparado com o do teste.
const CASES: [string, string, number][] = [["#197645", "#FFFFFF", 30], ["#8A5200", "#FFFFFF", 30], ["#B3261E", "#FFFFFF", 30], ["#5ED08E", "#171C25", 30], ["#F2B35B", "#171C25", 30], ["#FF8A80", "#171C25", 30]];

test("color-mix(in srgb) do navegador é igual à composição usada no teste de contraste", async ({ page }) => {
  await page.setContent("<div id=x></div>");
  for (const [a, b, p] of CASES) {
    const got = await page.evaluate(([fg, bg, pct]) => {
      const el = document.getElementById("x")!;
      el.style.backgroundColor = `color-mix(in srgb, ${fg} ${pct}%, ${bg})`;
      const c = getComputedStyle(el).backgroundColor;                       // "rgb(r, g, b)" ou "color(srgb r g b)"
      const m = c.match(/-?\d*\.?\d+/g)!.map(Number);
      return c.startsWith("color(") ? m.slice(0, 3).map((v) => Math.round(v * 255)) : m.slice(0, 3);
    }, [a, b, p] as const);
    const want = [1, 3, 5].map((i) => parseInt(mix(a, b, p / 100).slice(i, i + 2), 16));
    got.forEach((v, i) => expect(Math.abs(v - want[i]!), `${a}/${b} canal ${i}`).toBeLessThanOrEqual(1));   // ±1 por arredondamento
  }
});
