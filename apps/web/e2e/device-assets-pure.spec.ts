import { expect, test } from "@playwright/test";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { ASSETS, GENERIC_SRC, assetPath, resolveDeviceAsset, searchAssets, vendorsOf } from "../src/lib/deviceAssets";

// DeviceAssetRegistry (ADR-0041, PR1): funções puras e integridade do catálogo contra os arquivos reais de public/devices.
const PUB = join(__dirname, "..", "public");
const UNSAFE = /<script|\son\w+\s*=|javascript:|href\s*=\s*["']\s*(?:https?:)?\/\/|<foreignObject|<iframe|<object|<embed|<image[^>]+href\s*=\s*["']\s*(?:https?:)?\/\//i;

test("catálogo: 28 OLT + 41 ONU/ONT de 8 fabricantes, IDs únicos e todos os arquivos existem", () => {
  expect(ASSETS.filter((a) => a.device_type === "olt")).toHaveLength(28);
  expect(ASSETS.filter((a) => a.device_type === "onu_ont")).toHaveLength(41);
  expect(new Set(ASSETS.map((a) => a.asset_id)).size).toBe(ASSETS.length);
  expect(vendorsOf().map((v) => v.vendor)).toEqual(["datacom", "fiberhome", "huawei", "intelbras", "parks", "ubiquiti", "vsol", "zte"]);
  for (const a of ASSETS) {
    expect(a.svg).toBe(`/devices/svg/${a.asset_id}.svg`);
    expect(a.png).toBe(`/devices/png/${a.asset_id}.png`);
    expect(existsSync(join(PUB, assetPath(a.svg))), a.svg).toBe(true);
    expect(existsSync(join(PUB, assetPath(a.png))), a.png).toBe(true);
  }
  for (const g of Object.values(GENERIC_SRC)) expect(existsSync(join(PUB, g)), g).toBe(true);
});

test("nenhum SVG publicado tem script, handler, link externo ou conteúdo embutido; nenhum arquivo sobra sem registro", () => {
  const dir = join(PUB, "devices", "svg");
  const files = readdirSync(dir).filter((f) => f.endsWith(".svg"));
  expect(files.length).toBe(ASSETS.length + 2);   // o catálogo + os dois desenhos neutros por família
  for (const f of files) expect(UNSAFE.test(readFileSync(join(dir, f), "utf8")), f).toBe(false);
  const known = new Set([...ASSETS.map((a) => `${a.asset_id}.svg`), "generic-olt.svg", "generic-onu.svg"]);
  expect(files.filter((f) => !known.has(f))).toEqual([]);
  expect(readdirSync(join(PUB, "devices", "png")).length).toBe(ASSETS.length);
});

test("nenhuma arte afirma geometria verificada: todo o catálogo é esquemático e sem mapa físico homologado", () => {
  for (const a of ASSETS) {
    expect(a.accuracy, a.asset_id).toMatch(/not_model_exact/);
    expect(a.physical_mapping, a.asset_id).not.toMatch(/verified(?!_from)|homologated/);
    expect(resolveDeviceAsset({ vendor: a.vendor, model: a.model, category: a.device_type }).fidelity).toBe("SCHEMATIC");
  }
});

test("resolver: igualdade exata normalizada; sem prefixo, sem categoria trocada, sem arte de outro modelo", () => {
  const ok = resolveDeviceAsset({ vendor: "Huawei", model: "MA5608T", category: "olt" });
  expect([ok.match, ok.fidelity, ok.asset?.asset_id, ok.src]).toEqual(["exact", "SCHEMATIC", "olt-huawei-ma5608t", "/devices/svg/olt-huawei-ma5608t.svg"]);
  expect(resolveDeviceAsset({ vendor: " HUAWEI ", model: "ma-5608 t", category: "olt" }).asset?.asset_id).toBe("olt-huawei-ma5608t");
  expect(resolveDeviceAsset({ vendor: "Huawei Technologies", model: "MA5608T", category: "olt" }).asset?.asset_id).toBe("olt-huawei-ma5608t");
  for (const q of [{ vendor: "Huawei", model: "MA5608" }, { vendor: "Huawei", model: "MA5608T-X" }, { vendor: "Huawei", model: "" }, { vendor: "", model: "MA5608T" }, { vendor: null, model: null }, { vendor: "Outra", model: "MA5608T" }]) {
    const r = resolveDeviceAsset({ ...q, category: "olt" });
    expect([r.asset, r.fidelity, r.match, r.src]).toEqual([null, "UNKNOWN", "family", GENERIC_SRC.olt]);
  }
  const onu = ASSETS.find((a) => a.device_type === "onu_ont")!;
  expect(resolveDeviceAsset({ vendor: onu.vendor, model: onu.model, category: "olt" }).asset).toBeNull();   // um modelo de ONU não vira OLT
  expect(resolveDeviceAsset({ vendor: onu.vendor, model: onu.model, category: "onu_ont" }).asset?.asset_id).toBe(onu.asset_id);
  expect(resolveDeviceAsset({ vendor: "x", model: "y", category: "onu_ont" }).src).toBe(GENERIC_SRC.onu_ont);
});

test("o resultado nunca carrega geometria, porta, posição ou estado", () => {
  const r = resolveDeviceAsset({ vendor: "Huawei", model: "MA5608T", category: "olt" });
  expect(Object.keys(r).sort()).toEqual(["alt", "asset", "fidelity", "match", "src"]);
  expect(JSON.stringify(r)).not.toMatch(/"(ports?|slots?|geometry|x|y|led|status_port)"/i);
  expect(r.alt).toContain("ilustração esquemática");
});

test("caminhos de ativo: só local e do catálogo", () => {
  expect(assetPath("/devices/svg/olt-huawei-ma5608t.svg")).toBe("/devices/svg/olt-huawei-ma5608t.svg");
  for (const bad of ["http://x/y.svg", "https://x/y.svg", "//cdn/y.svg", "../a.svg", "/devices/../a.svg", "/a.svg?x=1", "/a.svg#f", "devices/a.svg", "C:\\a.svg", "javascript:alert(1)", "/a\\b.svg"]) {
    expect(() => assetPath(bad), bad).toThrow();
  }
});

test("busca por fabricante e modelo, com filtro de tipo e fabricante", () => {
  expect(searchAssets("huawei ma5608").map((a) => a.asset_id)).toContain("olt-huawei-ma5608t");
  expect(searchAssets("", { category: "olt" })).toHaveLength(28);
  expect(searchAssets("", { category: "onu_ont", vendor: "zte" }).every((a) => a.vendor === "zte" && a.device_type === "onu_ont")).toBe(true);
  expect(searchAssets("zzzzzz")).toEqual([]);
  expect(searchAssets("HUAWEI   ", { vendor: "Huawei Technologies" }).length).toBeGreaterThan(0);
});

test("a imagem de produção do web leva public/: sem isso o catálogo funciona em `next start` e dá 404 no LAB (standalone não copia public sozinho)", () => {
  const docker = readFileSync(join(__dirname, "..", "Dockerfile"), "utf8");
  expect(existsSync(join(PUB, "devices", "svg"))).toBe(true);
  const stages = docker.split(/^FROM /m).slice(1);   // cada estágio começa em `FROM`; a cópia precisa estar no ÚLTIMO (a imagem que roda)
  const last = stages[stages.length - 1]!;
  expect(last).toMatch(/^COPY --from=build \/app\/public \.\/public$/m);
  expect(last.indexOf("COPY --from=build /app/public")).toBeLessThan(last.indexOf("USER "));   // antes de largar o root: o arquivo existe e é legível pelo usuário da aplicação
  expect(stages.slice(0, -1).join("")).not.toMatch(/COPY --from=build \/app\/public/);        // e não só num estágio intermediário
});
