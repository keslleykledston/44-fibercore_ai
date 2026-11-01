import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { mix, ratio } from "../src/lib/contrast";
import { BAND_TINT } from "../src/lib/optics";

// Contraste WCAG dos tokens usados pela régua óptica e pelo restante da UI (funções puras, sem navegador). Lê os tokens de src/app/globals.css: se alguém clarear uma cor, o teste quebra.
const css = readFileSync(join(process.cwd(), "src/app/globals.css"), "utf-8");
const tokens = (block: string) => Object.fromEntries([...block.matchAll(/--([a-z0-9-]+):\s*(#[0-9A-Fa-f]{6})/g)].map((m) => [m[1]!, m[2]!]));
// os três blocos de tema são achados pelo SELETOR (não por posição de linha): claro, escuro automático (prefers-color-scheme) e escuro explícito (data-theme)
const blockOf = (re: RegExp) => { const m = css.match(re); if (!m) throw new Error(`bloco de tema não encontrado: ${re}`); return tokens(m[1]!); };
const light = blockOf(/^:root\s*\{([^}]*)\}/m);
const dark = blockOf(/:root\[data-theme="dark"\]\s*\{([^}]*)\}/);
const darkAuto = blockOf(/:root:not\(\[data-theme="light"\]\)\s*\{([^}]*)\}/);
const REQUIRED = ["bg", "surface", "surface-2", "accent-soft", "border", "ok", "warn", "danger", "ok-soft", "warn-soft", "danger-soft"];
test("os temas definem TODOS os tokens medidos e os dois blocos escuros são iguais", () => {
  for (const [name, t] of [["claro", light], ["escuro", dark], ["escuro automático", darkAuto]] as const) for (const k of REQUIRED) expect(t[k], `${k} no tema ${name}`).toBeDefined();
  for (const k of REQUIRED) expect(darkAuto[k], `${k}: escuro automático = escuro explícito`).toBe(dark[k]);
});

for (const [name, t] of [["claro", light], ["escuro", dark]] as const) {
  test(`tema ${name}: ok, warn e danger têm 4,5:1 como TEXTO sobre as superfícies da UI`, () => {
    for (const tone of ["ok", "warn", "danger"]) {
      for (const bg of ["surface", "surface-2", "accent-soft", "bg", "ok-soft", "warn-soft", "danger-soft"]) expect(ratio(t[tone]!, t[bg]!), `${tone} sobre ${bg}`).toBeGreaterThanOrEqual(4.5);
    }
  });
  test(`tema ${name}: ok, warn e danger têm 3:1 como FUNDO ou BORDA (bg-ok, border-danger…) contra as superfícies vizinhas`, () => {
    for (const tone of ["ok", "warn", "danger"]) {
      for (const bg of ["surface", "surface-2", "bg"]) expect(ratio(t[tone]!, t[bg]!), `${tone} contra ${bg}`).toBeGreaterThanOrEqual(3);
    }
  });
  test(`tema ${name}: o marcador da régua tem 3:1 contra a faixa da mesma cor`, () => {
    for (const tone of ["ok", "warn", "danger"]) expect(ratio(t[tone]!, mix(t[tone]!, t["surface"]!, BAND_TINT / 100)), tone).toBeGreaterThanOrEqual(3);
  });
}
