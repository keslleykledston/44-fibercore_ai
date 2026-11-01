import { ariaLabel, AXIS_MAX, AXIS_MIN, fmtDbm, LEVEL_TEXT, LIMITS, opticalView, position, REFERENCE_NOTICE } from "@/lib/optics";

const pct = (v: number) => `${position(v).toFixed(2)}%`;
const tint = (tone: string, n: number) => `color-mix(in srgb, var(--${tone}) ${n}%, var(--surface))`;
// gradiente suave perigo → aviso → ok → aviso → perigo, com as transições centradas nos limites
const GRADIENT = `linear-gradient(to right, ${tint("danger", 38)} 0%, ${tint("danger", 38)} calc(${pct(LIMITS.weak)} - 2%), ${tint("warn", 38)} calc(${pct(LIMITS.weak)} + 2%), ${tint("warn", 38)} calc(${pct(LIMITS.lowMargin)} - 2%), ${tint("ok", 38)} calc(${pct(LIMITS.lowMargin)} + 2%), ${tint("ok", 38)} calc(${pct(LIMITS.strong)} - 1%), ${tint("warn", 38)} calc(${pct(LIMITS.strong)} + 1%), ${tint("warn", 38)} calc(${pct(LIMITS.overload)} - 1%), ${tint("danger", 38)} calc(${pct(LIMITS.overload)} + 1%), ${tint("danger", 38)} 100%)`;
const TICKS = [LIMITS.weak, LIMITS.lowMargin, LIMITS.strong, LIMITS.overload] as const;

export type RulerSize = "lg" | "md" | "sm";

/** Régua de nível óptico recebido (ADR-0037, emenda de 2026-11-01). Três tamanhos: lg (página de Diagnóstico), md (painel lateral), sm (linha de tabela: marcador e rótulo). A cor nunca é o único
 *  sinal: rótulo e símbolo sempre; valor defasado ou ausente não é classificado. O marcador não anima. `agoText` = "há 2 h" etc., já formatado por quem chama. */
export function OpticalRuler({ rx, freshness, agoText = null, size = "md" }: { rx: number | null | undefined; freshness: string | null | undefined; agoText?: string | null; size?: RulerSize }) {
  const v = opticalView(rx, freshness);
  const info = v.kind === "read" ? LEVEL_TEXT[v.level] : null;
  const toneVar = info ? `var(--${info.tone})` : "var(--muted)";
  const label = v.kind === "none" ? "Sem leitura de sinal" : v.kind === "stale" ? `Último valor conhecido${agoText ? ` · ${agoText}` : ""}` : `${info!.symbol} ${info!.label}`;
  const number = v.kind === "none" ? "—" : fmtDbm(v.rx);
  const aria = ariaLabel(v, agoText);

  if (size === "sm") {
    return (
      <span className="inline-flex items-center gap-2 text-xs" data-testid="optical-ruler" data-size="sm" data-state={v.kind === "read" ? v.level : v.kind} role="img" aria-label={aria}>
        <span aria-hidden className="relative inline-block h-2 w-16 rounded-full border border-line" style={{ background: GRADIENT }}>
          {v.kind !== "none" && <span className="absolute top-1/2 h-3 w-1.5 -translate-x-1/2 -translate-y-1/2 rounded-sm border-2" style={{ left: pct(v.rx), borderColor: toneVar, background: v.kind === "read" ? toneVar : "transparent" }} />}
        </span>
        <span aria-hidden style={{ color: v.kind === "read" ? toneVar : undefined }} className={v.kind === "read" ? "font-medium" : "text-muted"}>{label}</span>
      </span>
    );
  }
  const big = size === "lg";
  return (
    <div className="grid gap-1" data-testid="optical-ruler" data-size={size} data-state={v.kind === "read" ? v.level : v.kind}>
      <div role="img" aria-label={aria} className="grid gap-1">
      <div aria-hidden className="flex flex-wrap items-baseline justify-between gap-x-3">
        <span className={`${big ? "text-2xl" : "text-lg"} font-semibold tabular-nums`} data-testid="optical-ruler-number">{number}</span>
        <span className={`${big ? "text-sm" : "text-xs"} font-medium ${v.kind === "read" ? "" : "text-muted"}`} style={{ color: v.kind === "read" ? toneVar : undefined }} data-testid="optical-ruler-label">{label}</span>
      </div>
      <div aria-hidden className={`relative ${big ? "mt-4 h-4" : "mt-3 h-3"} rounded-full border border-line ${v.kind === "none" ? "opacity-50" : ""}`} style={{ background: GRADIENT }}>
        {TICKS.map((t) => <span key={t} className="absolute top-0 h-full w-px bg-[color:var(--muted)] opacity-60" style={{ left: pct(t) }} />)}
        {v.kind !== "none" && (
          <span className="absolute -top-3.5 -translate-x-1/2 text-xs leading-none" style={{ left: pct(v.rx), color: toneVar }} data-testid="optical-ruler-marker">
            <span className="block text-center">{v.kind === "stale" ? "▽" : "▼"}</span>
          </span>
        )}
      </div>
      <div aria-hidden className="relative h-4 text-[10px] text-muted tabular-nums">
        <span className="absolute left-0">{AXIS_MIN}</span>
        {TICKS.map((t) => <span key={t} className="absolute -translate-x-1/2" style={{ left: pct(t) }}>{t}</span>)}
        <span className="absolute right-0">{AXIS_MAX}</span>
      </div>
      </div>
      <p className="text-[11px] text-muted" data-testid="optical-ruler-notice">{REFERENCE_NOTICE}{v.kind === "stale" ? " O valor está defasado: o nível atual não é classificado." : ""}</p>
    </div>
  );
}
