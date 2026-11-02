import manifest from "./deviceAssets.manifest.json";

/**
 * DeviceAssetRegistry (ADR-0041, PR1): ilustrações ESQUEMÁTICAS e originais por fabricante+modelo. Regras que este arquivo garante:
 *  - uma imagem NUNCA é prova de suporte: `fidelity` é sempre `SCHEMATIC` (ou `UNKNOWN` no fallback) e `MODEL_VERIFIED` não existe aqui, só um mapa homologado de portas o merece;
 *  - o resolver devolve arte e rótulo, JAMAIS geometria, numeração ou posição de porta (isso vem do inventário/driver);
 *  - só caminhos locais do catálogo (nada de URL externa), e modelo desconhecido cai num desenho NEUTRO por família, nunca na arte de outro modelo.
 */
export type DeviceCategory = "olt" | "onu_ont";
export type Fidelity = "SCHEMATIC" | "UNKNOWN";
export type DeviceAsset = {
  asset_id: string; device_type: DeviceCategory; vendor: string; model: string; technology: string | null; svg: string; png: string; port_count_nominal: number | null;
  style: string | null; accuracy: string; physical_mapping: string; status: string; source_urls: string[];
};
export type Resolved = { asset: DeviceAsset | null; src: string; fidelity: Fidelity; match: "exact" | "family"; alt: string };

export const ASSETS: readonly DeviceAsset[] = manifest.assets as DeviceAsset[];
export const GENERIC_SRC: Record<DeviceCategory, string> = { olt: "/devices/svg/generic-olt.svg", onu_ont: "/devices/svg/generic-onu.svg" };
export const FIDELITY_LABEL: Record<Fidelity, string> = { SCHEMATIC: "Ilustração esquemática", UNKNOWN: "Sem arte catalogada" };
export const FIDELITY_NOTE = "Não é foto nem desenho exato do modelo, e não mostra portas reais: portas, placas e estados vêm do inventário da OLT.";

const clean = (s: string) => s.normalize("NFKD").toLowerCase().replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]/g, "");
// só apelidos inequívocos de razão social: qualquer outro nome não resolve (nunca adivinhar fabricante)
const VENDOR_ALIAS: Record<string, string> = { huaweitechnologies: "huawei", ubiquitinetworks: "ubiquiti", ubnt: "ubiquiti", ztecorporation: "zte", ztecorp: "zte" };
const vendorKey = (v: string) => { const c = clean(v); return VENDOR_ALIAS[c] ?? c; };

/** Caminho local de um ativo do catálogo (começa com `/`, sem `..`, `?`, `#`, `//` nem protocolo): qualquer outra forma é recusada. */
export function assetPath(path: string): string {
  if (!path.startsWith("/") || path.startsWith("//") || path.includes("..") || /[?#:\\]/.test(path)) throw new Error("Invalid catalog asset path");
  return path;
}

export function resolveDeviceAsset(q: { vendor?: string | null; model?: string | null; category: DeviceCategory }, assets: readonly DeviceAsset[] = ASSETS): Resolved {
  const v = vendorKey(q.vendor ?? ""), m = clean(q.model ?? "");
  const hit = v && m ? assets.find((a) => a.device_type === q.category && vendorKey(a.vendor) === v && clean(a.model) === m) ?? null : null;   // igualdade exata: sem aproximação por prefixo
  if (hit) return { asset: hit, src: assetPath(hit.svg), fidelity: "SCHEMATIC", match: "exact", alt: `${hit.vendor} ${hit.model}: ilustração esquemática` };
  return { asset: null, src: GENERIC_SRC[q.category], fidelity: "UNKNOWN", match: "family", alt: q.category === "olt" ? "OLT genérica: sem arte catalogada para este modelo" : "ONU/ONT genérica: sem arte catalogada para este modelo" };
}

export function searchAssets(query: string, f: { category?: DeviceCategory | null; vendor?: string | null } = {}, assets: readonly DeviceAsset[] = ASSETS): DeviceAsset[] {
  const tokens = query.split(/\s+/).map(clean).filter(Boolean);
  const vk = f.vendor ? vendorKey(f.vendor) : "";
  return assets.filter((a) => (!f.category || a.device_type === f.category) && (!vk || vendorKey(a.vendor) === vk)
    && tokens.every((t) => clean(`${a.vendor} ${a.model} ${a.technology ?? ""}`).includes(t)));
}

export function vendorsOf(assets: readonly DeviceAsset[] = ASSETS): { vendor: string; olt: number; onu_ont: number }[] {
  const by = new Map<string, { vendor: string; olt: number; onu_ont: number }>();
  for (const a of assets) { const e = by.get(a.vendor) ?? { vendor: a.vendor, olt: 0, onu_ont: 0 }; e[a.device_type] += 1; by.set(a.vendor, e); }
  return [...by.values()].sort((x, y) => x.vendor.localeCompare(y.vendor));
}

export const VENDOR_LABEL: Record<string, string> = { huawei: "Huawei", datacom: "Datacom", zte: "ZTE", fiberhome: "FiberHome", intelbras: "Intelbras", vsol: "V-SOL", ubiquiti: "Ubiquiti", parks: "Parks" };
