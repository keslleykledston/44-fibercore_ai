/** Faixas de REFERÊNCIA do nível óptico recebido pela ONU (ITU-T G.984.2 classe B+: sensibilidade −28 dBm, sobrecarga −8 dBm). Só apresentação (ADR-0037, emenda de 2026-11-01):
 *  a API não julga o Rx, e estes limites NÃO estão homologados para nenhuma OLT/óptica. Valor defasado ou ausente nunca é classificado. */
/** Intensidade (%) da cor de cada faixa da régua sobre a superfície. 30 % mantém o marcador (cor cheia da mesma faixa) acima de 3:1 nos dois temas (WCAG 1.4.11); ver e2e/optics-contrast.spec.ts. */
export const BAND_TINT = 30;
export const AXIS_MIN = -34;
export const AXIS_MAX = -3;
/** Limites únicos (dBm). Abaixo de WEAK: crítico fraco; [WEAK, LOW_MARGIN): atenção; [LOW_MARGIN, STRONG]: bom; (STRONG, OVERLOAD]: atenção; acima de OVERLOAD: crítico. */
export const LIMITS = { weak: -28, lowMargin: -25, strong: -10, overload: -8 } as const;
export const REFERENCE_NOTICE = "Faixa de referência do padrão (G.984.2 classe B+). Não homologada para esta OLT/óptica.";

export type OpticalLevel = "critical_low" | "warn_low" | "good" | "warn_high" | "critical_high";
export type OpticalView =
  | { kind: "none" }
  | { kind: "stale"; rx: number }
  | { kind: "read"; rx: number; level: OpticalLevel };

export const LEVEL_TEXT: Record<OpticalLevel, { label: string; symbol: "✓" | "!" | "✕"; tone: "ok" | "warn" | "danger" }> = {
  critical_low: { label: "Crítico · sinal fraco", symbol: "✕", tone: "danger" },
  warn_low: { label: "Atenção · margem baixa", symbol: "!", tone: "warn" },
  good: { label: "Bom", symbol: "✓", tone: "ok" },
  warn_high: { label: "Atenção · sinal forte", symbol: "!", tone: "warn" },
  critical_high: { label: "Crítico · sobrecarga", symbol: "✕", tone: "danger" },
};

export function classify(rx: number): OpticalLevel {
  if (rx < LIMITS.weak) return "critical_low";
  if (rx < LIMITS.lowMargin) return "warn_low";
  if (rx <= LIMITS.strong) return "good";
  if (rx <= LIMITS.overload) return "warn_high";
  return "critical_high";
}

/** Posição (0–100 %) de um valor no eixo; fora do eixo fica na ponta (o número escrito continua sendo o real). */
export function position(rx: number): number {
  return Math.min(100, Math.max(0, ((rx - AXIS_MIN) / (AXIS_MAX - AXIS_MIN)) * 100));
}

/** O que a tela pode afirmar: só um valor FRESCO e finito é classificado; defasado = último valor conhecido; sem número = sem leitura. */
export function opticalView(rx: number | null | undefined, freshness: string | null | undefined): OpticalView {
  if (typeof rx !== "number" || !Number.isFinite(rx)) return { kind: "none" };
  if (freshness !== "fresh") return { kind: "stale", rx };
  return { kind: "read", rx, level: classify(rx) };
}

export const fmtDbm = (rx: number): string => `${rx.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} dBm`;

export function ariaLabel(v: OpticalView, ago: string | null): string {
  if (v.kind === "none") return "Sem leitura de sinal óptico";
  if (v.kind === "stale") return `Último valor conhecido: ${fmtDbm(v.rx)}${ago ? `, ${ago}` : ""}. Dado defasado: o nível atual não é classificado`;
  return `Nível óptico ${fmtDbm(v.rx)}: ${LEVEL_TEXT[v.level].label.toLowerCase()}. Referência G.984.2 classe B+`;
}
