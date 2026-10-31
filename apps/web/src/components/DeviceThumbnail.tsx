/** Miniatura GENÉRICA do aparelho (SVG local, sem asset de fabricante). Os dois pontos de luz NÃO são os LEDs reais: são a leitura da PON (esquerda) e do ACS (direita),
 *  cada um só colorido quando há observação fresca; sem dado ficam neutros. O texto ao lado sempre diz o estado (a cor é só reforço). */
export type Tone = "ok" | "warn" | "bad" | "neutral";
const COLOR: Record<Tone, string> = { ok: "var(--ok, #2e7d32)", warn: "var(--warn, #b26a00)", bad: "var(--danger, #c62828)", neutral: "currentColor" };

export function DeviceThumbnail({ pon = "neutral", acs = "neutral", height = 96 }: { pon?: Tone; acs?: Tone; height?: number }) {
  return (
    <svg role="img" aria-label="Representação genérica do dispositivo" viewBox="0 0 160 96" height={height} className="text-muted" data-testid="ont-thumbnail" data-pon={pon} data-acs={acs}>
      <rect x="14" y="48" width="132" height="34" rx="10" fill="none" stroke="currentColor" strokeWidth="2.5" />
      <circle cx="40" cy="65" r="5" fill={COLOR[pon]} opacity={pon === "neutral" ? 0.35 : 1} />
      <circle cx="60" cy="65" r="5" fill={COLOR[acs]} opacity={acs === "neutral" ? 0.35 : 1} />
      <circle cx="80" cy="65" r="5" fill="currentColor" opacity=".2" />
      <path d="M44 48 28 16M116 48l16-32" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  );
}
