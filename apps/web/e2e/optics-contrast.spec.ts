import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { BAND_TINT } from "../src/lib/optics";

// Contraste WCAG dos tokens usados pela régua óptica e pelo restante da UI (funções puras, sem navegador). Lê os tokens de src/app/globals.css: se alguém clarear uma cor, o teste quebra.
const css = readFileSync(join(process.cwd(), "src/app/globals.css"), "utf-8");
const tokens = (block: string) => Object.fromEntries([...block.matchAll(/--([a-z0-9-]+):\s*(#[0-9A-Fa-f]{6})/g)].map((m) => [m[1]!, m[2]!]));
const lines = css.split("\n");
const light = tokens(lines.slice(4, 9).join("\n"));
const dark = tokens(lines.slice(16, 19).join("\n"));
const lum = (hex: string) => {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!;
};
const ratio = (a: string, b: string) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x! + 0.05) / (y! + 0.05); };
const mix = (a: string, b: string, p: number) => "#" + [1, 3, 5].map((i) => Math.round(parseInt(a.slice(i, i + 2), 16) * p + parseInt(b.slice(i, i + 2), 16) * (1 - p)).toString(16).padStart(2, "0")).join("");

for (const [name, t] of [["claro", light], ["escuro", dark]] as const) {
  test(`tema ${name}: ok, warn e danger têm 4,5:1 como TEXTO sobre as superfícies da UI`, () => {
    for (const tone of ["ok", "warn", "danger"]) {
      for (const bg of ["surface", "surface-2", "accent-soft", "bg", "ok-soft", "warn-soft", "danger-soft"]) {
        if (!t[bg]) continue;
        expect(ratio(t[tone]!, t[bg]!), `${tone} sobre ${bg}`).toBeGreaterThanOrEqual(4.5);
      }
    }
  });
  test(`tema ${name}: o marcador da régua tem 3:1 contra a faixa da mesma cor`, () => {
    for (const tone of ["ok", "warn", "danger"]) expect(ratio(t[tone]!, mix(t[tone]!, t["surface"]!, BAND_TINT / 100)), tone).toBeGreaterThanOrEqual(3);
  });
}
