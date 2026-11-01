import { expect, test } from "@playwright/test";
import { ariaLabel, classify, fmtDbm, LIMITS, opticalView, position } from "../src/lib/optics";

// Funções puras da régua óptica (ADR-0037, emenda de 2026-11-01). Não abrem navegador nem tocam a API.
test("as faixas de referência G.984.2 classe B+ respeitam os limites e quem pertence a cada lado", () => {
  expect(LIMITS).toEqual({ weak: -28, lowMargin: -25, strong: -10, overload: -8 });
  const cases: [number, string][] = [
    [-34, "critical_low"], [-28.01, "critical_low"], [-28, "warn_low"], [-26.5, "warn_low"], [-25.01, "warn_low"],
    [-25, "good"], [-14.66, "good"], [-13.04, "good"], [-10, "good"],
    [-9.99, "warn_high"], [-8, "warn_high"], [-7.99, "critical_high"], [-3, "critical_high"], [0, "critical_high"],
  ];
  for (const [rx, level] of cases) expect(classify(rx), String(rx)).toBe(level);
});

test("a posição fica no eixo de −34 a −3 dBm e valores fora dele ficam na ponta", () => {
  expect(position(-34)).toBe(0);
  expect(position(-3)).toBe(100);
  expect(position(-50)).toBe(0);
  expect(position(5)).toBe(100);
  expect(position(-18.5)).toBeCloseTo(50, 5);
});

test("só um valor fresco é classificado; defasado e ausente nunca viram faixa", () => {
  expect(opticalView(-14.66, "fresh")).toEqual({ kind: "read", rx: -14.66, level: "good" });
  for (const f of ["stale", "unknown", null, undefined, ""]) expect(opticalView(-14.66, f as string | null)).toEqual({ kind: "stale", rx: -14.66 });
  for (const rx of [null, undefined, Number.NaN, Number.POSITIVE_INFINITY]) expect(opticalView(rx as number | null, "fresh")).toEqual({ kind: "none" });
});

test("o texto acessível diz valor, faixa e referência, e não afirma nada sobre dado defasado", () => {
  expect(fmtDbm(-14.66)).toBe("-14,66 dBm");
  expect(ariaLabel(opticalView(-14.66, "fresh"), null)).toBe("Nível óptico -14,66 dBm: bom. Referência G.984.2 classe B+");
  const stale = ariaLabel(opticalView(-14.66, "stale"), "há 2 h");
  expect(stale).toContain("Último valor conhecido");
  expect(stale).not.toMatch(/bom|atenção|crítico/i);
  expect(ariaLabel({ kind: "none" }, null)).toBe("Sem leitura de sinal óptico");
});
