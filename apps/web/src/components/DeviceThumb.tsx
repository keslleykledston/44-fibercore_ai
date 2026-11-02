import { FIDELITY_LABEL, resolveDeviceAsset, type DeviceCategory } from "@/lib/deviceAssets";

/** Miniatura de um equipamento pela arte esquemática do catálogo (ou o desenho neutro da família). Mostra rótulo de fidelidade e NUNCA portas, LEDs ou estados. `decorative`: ao lado do nome do modelo (alt vazio). */
export function DeviceThumb({ category, vendor, model, width = 72, decorative = false, label = false }: { category: DeviceCategory; vendor?: string | null; model?: string | null; width?: number; decorative?: boolean; label?: boolean }) {
  const r = resolveDeviceAsset({ category, vendor, model });
  return (
    <figure className="m-0 inline-flex flex-col items-center gap-1" data-testid="device-thumb" data-fidelity={r.fidelity} data-match={r.match} data-asset={r.asset?.asset_id ?? "generic"}>
      {/* eslint-disable-next-line @next/next/no-img-element -- ilustração local e estática do catálogo: sem otimizador */}
      <img src={r.src} alt={decorative ? "" : r.alt} width={width} height={Math.round(width * 0.75)} loading="lazy" decoding="async" className="h-auto max-w-full" />
      {label && <figcaption className="text-xs text-muted">{FIDELITY_LABEL[r.fidelity]}</figcaption>}
    </figure>
  );
}
