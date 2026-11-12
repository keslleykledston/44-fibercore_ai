import { expect, test } from "@playwright/test";
import { buildCsp, cspHeaderName, cspMode, generateNonce, safeReportUri } from "../src/lib/csp";

// Gerador de política CSP (ADR-0042). Funções puras: sem navegador nem API.
const NONCE = "AAAAAAAAAAAAAAAAAAAAAA==";
const dirs = (csp: string) => Object.fromEntries(csp.split("; ").map((d) => { const [k, ...v] = d.split(" "); return [k, v.join(" ")]; }));

test("política de produção: scripts só com nonce + strict-dynamic, sem unsafe-inline/unsafe-eval; estilo de elemento só com nonce", () => {
  const d = dirs(buildCsp({ nonce: NONCE }));
  expect(d["script-src"]).toBe(`'self' 'nonce-${NONCE}' 'strict-dynamic'`);
  expect(d["style-src"]).toBe(`'self' 'nonce-${NONCE}'`);
  expect(d["default-src"]).toBe("'self'");
  expect(d["object-src"]).toBe("'none'");
  expect(d["base-uri"]).toBe("'self'");
  expect(d["frame-ancestors"]).toBe("'none'");
  expect(d["form-action"]).toBe("'self'");
  expect(d["connect-src"]).toBe("'self'");
  expect(d["img-src"]).toBe("'self' data:");   // sem blob:, sem https:
  expect(d["font-src"]).toBe("'self'");
  for (const k of ["script-src", "style-src", "default-src", "connect-src", "img-src"]) expect(d[k], k).not.toContain("unsafe-inline");
  expect(d["script-src"]).not.toContain("unsafe-eval");
});

test("o ÚNICO unsafe-inline que sobra é style-src-attr (atributos style= renderizados no servidor)", () => {
  const csp = buildCsp({ nonce: NONCE });
  const withInline = csp.split("; ").filter((x) => x.includes("'unsafe-inline'")).map((x) => x.split(" ")[0]);
  expect(withInline).toEqual(["style-src-attr"]);
  expect(csp).not.toMatch(/\*|https?:/);   // nenhum curinga nem origem externa
});

test("dev relaxa só o necessário (unsafe-eval em script, ws em connect); produção não", () => {
  const dev = dirs(buildCsp({ nonce: NONCE, dev: true }));
  expect(dev["script-src"]).toContain("'unsafe-eval'");
  expect(dev["connect-src"]).toContain("ws:");
  const prod = dirs(buildCsp({ nonce: NONCE, dev: false }));
  expect(prod["script-src"]).not.toContain("unsafe-eval");
  expect(prod["connect-src"]).not.toContain("ws:");
});

test("nonce: 128 bits, base64, único a cada chamada; nonce malformado é recusado (não vira injeção de diretiva)", () => {
  const seen = new Set(Array.from({ length: 200 }, () => generateNonce()));
  expect(seen.size).toBe(200);
  for (const n of seen) { expect(n).toMatch(/^[A-Za-z0-9+/]{22}==$/); expect(atob(n).length).toBe(16); }
  expect(generateNonce((b) => b.fill(0))).toBe(NONCE);
  for (const bad of ["", "abc", "x'; script-src *; '", `${NONCE}'`, "A".repeat(40)]) expect(() => buildCsp({ nonce: bad }), bad).toThrow();
});

test("modo: padrão report-only; só 'enforce' e 'off' mudam; lixo cai no padrão seguro; cabeçalho correspondente", () => {
  expect(cspMode(undefined)).toBe("report-only");
  expect(cspMode("")).toBe("report-only");
  expect(cspMode("report-only")).toBe("report-only");
  expect(cspMode("ENFORCE")).toBe("enforce");
  expect(cspMode(" enforce ")).toBe("enforce");
  expect(cspMode("off")).toBe("off");
  expect(cspMode("true")).toBe("report-only");
  expect(cspHeaderName("enforce")).toBe("Content-Security-Policy");
  expect(cspHeaderName("report-only")).toBe("Content-Security-Policy-Report-Only");
});

test("report-uri: só caminho absoluto ou https simples; qualquer coisa que injete diretiva é descartada", () => {
  expect(safeReportUri("/csp-report")).toBe("/csp-report");
  expect(safeReportUri("https://report.example.com/r")).toBe("https://report.example.com/r");
  for (const bad of [undefined, "", "http://x.example/r", "//x.example/r", "/r; script-src *", "/r, other", "/r 'unsafe-inline'", "javascript:alert(1)", "https://x.example/r;x"]) expect(safeReportUri(bad), String(bad)).toBeNull();
  const d = dirs(buildCsp({ nonce: NONCE, reportUri: "/csp-report" }));
  expect(d["report-uri"]).toBe("/csp-report");
  expect(dirs(buildCsp({ nonce: NONCE }))["report-uri"]).toBeUndefined();
});
