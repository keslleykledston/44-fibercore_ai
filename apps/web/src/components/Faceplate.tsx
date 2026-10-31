"use client";

import { useId } from "react";
import { faceplateFor, LED_STATE_LABELS, miniLeds, readLeds, type FaceplateLed, type FaceplatePort, type LedRole, type LedState, type Reported } from "@/lib/faceplates";

/** Painel frontal vetorial e acessível (ADR-0037, padrão do protótipo Lovable). O desenho é DERIVADO do status reportado, nunca de uma leitura LED a LED;
 *  cor nunca é o único indicador (cada LED tem rótulo e a legenda diz o estado em texto). */
const W = 480, H = 172, CW = 330, ROW_H = 46, CHUNK = 5, PAD = 30, RAIL_Y = 56, PORT_Y = 122;
const spread = (n: number, from: number, to: number) => (n <= 1 ? [(from + to) / 2] : Array.from({ length: n }, (_, i) => from + ((to - from) * i) / (n - 1)));
const toneOf = (role: LedRole) => (role === "optical-fault" ? "var(--danger)" : role === "wireless" || role === "pairing" ? "var(--accent)" : "var(--ok)");
const lit = (s: LedState) => s === "on" || s === "blink" || s === "blink-fast";

function LedDot({ x, y, state, tone, r = 5.5 }: { x: number; y: number; state: LedState; tone: string; r?: number }) {
  if (state === "unknown") return <g><circle cx={x} cy={y} r={r} fill="none" stroke="var(--muted)" strokeWidth={1.2} strokeDasharray="2 2" /><circle cx={x} cy={y} r={1.4} fill="var(--muted)" /></g>;
  if (!lit(state)) return <circle cx={x} cy={y} r={r} fill="var(--surface-2)" stroke="var(--muted)" strokeOpacity={0.65} strokeWidth={1.2} />;
  return (
    <g className={state === "blink" ? "fp-blink" : state === "blink-fast" ? "fp-blink-fast" : undefined}>
      <circle cx={x} cy={y} r={r * 2} fill={tone} opacity={0.16} /><circle cx={x} cy={y} r={r} fill={tone} /><circle cx={x - r * 0.3} cy={y - r * 0.3} r={r * 0.28} fill="var(--surface)" opacity={0.55} />
    </g>
  );
}

function PortShape({ kind, x, y }: { kind: FaceplatePort["kind"]; x: number; y: number }) {
  const s = "var(--border)", b = "var(--surface-2)";
  switch (kind) {
    case "power": return <g><circle cx={x} cy={y} r={7} fill={b} stroke={s} /><circle cx={x} cy={y} r={2.4} fill="var(--surface)" stroke={s} /></g>;
    case "sc": return <g><rect x={x - 11} y={y - 8} width={22} height={16} rx={2} fill={b} stroke={s} /><rect x={x - 4} y={y - 4} width={8} height={8} rx={1} fill="var(--accent-soft)" stroke={s} /></g>;
    case "rj45": return <g><rect x={x - 13} y={y - 9} width={26} height={18} rx={2} fill={b} stroke={s} /><rect x={x - 5} y={y + 6} width={10} height={4} fill={b} stroke={s} /><line x1={x - 8} y1={y - 4} x2={x + 8} y2={y - 4} stroke={s} /></g>;
    case "rj11": return <g><rect x={x - 8} y={y - 7} width={16} height={14} rx={2} fill={b} stroke={s} /><line x1={x - 4} y1={y - 2} x2={x + 4} y2={y - 2} stroke={s} /></g>;
    case "usb": return <g><rect x={x - 10} y={y - 5} width={20} height={10} rx={1.5} fill={b} stroke={s} /><rect x={x - 6} y={y - 1} width={12} height={3} fill="var(--surface)" stroke={s} /></g>;
    case "button": return <rect x={x - 8} y={y - 4} width={16} height={8} rx={4} fill={b} stroke={s} />;
    case "pinhole": return <circle cx={x} cy={y} r={2.6} fill="var(--surface)" stroke={s} />;
  }
}

export function Faceplate({ model, reported, label, compact = false }: { model: string | null | undefined; reported: Reported; label?: string; compact?: boolean }) {
  const fp = faceplateFor(model);
  const reading = readLeds(fp, reported);
  const patternId = useId();
  const rows: FaceplateLed[][] = compact ? Array.from({ length: Math.ceil(fp.leds.length / CHUNK) }, (_, r) => fp.leds.slice(r * CHUNK, (r + 1) * CHUNK)) : [fp.leds];
  const w = compact ? CW : W;
  const h = compact ? 24 + rows.length * ROW_H + 14 : H;
  const portX = spread(fp.ports.length, PAD + 14, W - PAD - 14);
  const cls = compact ? "fp-label-lg" : "fp-label";
  const rowY = (r: number) => (compact ? 44 + r * ROW_H : RAIL_Y);
  const rowX = (n: number) => spread(n, compact ? 34 : PAD + 12, w - (compact ? 34 : PAD + 12));
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full" role="img" aria-label={`${label ?? fp.model}: ${reading.summary}`} data-testid="faceplate" data-last-known={reading.lastKnown ? "true" : "false"}>
      <defs><pattern id={patternId} width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="7" stroke="var(--border)" strokeWidth="1.4" /></pattern></defs>
      <rect x={7} y={7} width={w - 14} height={h - 14} rx={14} fill="var(--surface)" stroke="var(--border)" />
      <rect x={13} y={13} width={w - 26} height={h - 26} rx={11} fill="none" stroke="var(--border)" opacity={0.5} />
      <text x={compact ? 20 : PAD} y={compact ? 26 : 30} className={cls} fill="var(--muted)">{fp.model}</text>
      <text x={w - (compact ? 20 : PAD)} y={compact ? 26 : 30} textAnchor="end" className={cls} fill="var(--muted)">conceitual</text>
      {reading.lastKnown && <rect x={compact ? 16 : PAD} y={rowY(0) - 16} width={w - (compact ? 32 : PAD * 2)} height={compact ? rows.length * ROW_H + 2 : 30} rx={6} fill={`url(#${patternId})`} opacity={0.55} />}
      {rows.map((row, r) => {
        const xs = rowX(row.length), y = rowY(r);
        return (
          <g key={`linha-${r}`}>
            {row.map((l, i) => (
              <g key={l.id}>
                <LedDot x={xs[i] ?? 0} y={y} state={reading.leds[l.id] ?? "unknown"} tone={toneOf(l.role)} r={compact ? 6.5 : 5.5} />
                <text x={xs[i] ?? 0} y={y + (compact ? 26 : 22)} textAnchor="middle" className={cls} fill="var(--muted)">{l.label}</text>
              </g>
            ))}
          </g>
        );
      })}
      {!compact && (
        <>
          <line x1={PAD} y1={PORT_Y - 26} x2={W - PAD} y2={PORT_Y - 26} stroke="var(--border)" opacity={0.7} />
          {fp.ports.map((p, i) => (
            <g key={p.id}><PortShape kind={p.kind} x={portX[i] ?? 0} y={PORT_Y} /><text x={portX[i] ?? 0} y={PORT_Y + 22} textAnchor="middle" className="fp-label" fill="var(--muted)">{p.label}</text></g>
          ))}
        </>
      )}
    </svg>
  );
}

function Glyph({ state, tone }: { state: LedState; tone: string }) {
  if (state === "unknown") return <span className="mt-1 size-3 shrink-0 rounded-full border border-dashed border-muted" aria-hidden />;
  if (!lit(state)) return <span className="mt-1 size-3 shrink-0 rounded-full border border-line bg-surface-2" aria-hidden />;
  return <span className={`mt-1 size-3 shrink-0 rounded-full ${state === "blink" ? "fp-blink" : state === "blink-fast" ? "fp-blink-fast" : ""}`} style={{ background: tone }} aria-hidden />;
}

/** Legenda em texto: o estado de cada LED por extenso. */
export function FaceplateLegend({ model, reported }: { model: string | null | undefined; reported: Reported }) {
  const fp = faceplateFor(model);
  const reading = readLeds(fp, reported);
  return (
    <ul className="grid gap-x-6 gap-y-2 sm:grid-cols-2" data-testid="faceplate-legend">
      {fp.leds.map((l) => {
        const s = reading.leds[l.id] ?? "unknown";
        return (
          <li key={l.id} className="flex gap-2 text-xs leading-relaxed">
            <Glyph state={s} tone={toneOf(l.role)} />
            <span className="min-w-0"><span className="font-medium">{l.label} · {LED_STATE_LABELS[s]}</span><span className="block text-muted">{l.meaning}</span></span>
          </li>
        );
      })}
    </ul>
  );
}

/** Miniatura para listas e cabeçalhos. */
export function FaceplateMini({ model, reported, label }: { model: string | null | undefined; reported: Reported; label?: string }) {
  const fp = faceplateFor(model);
  const reading = readLeds(fp, reported);
  const leds = miniLeds(fp);
  const xs = spread(leds.length, 12, 60);
  return (
    <svg viewBox="0 0 72 20" className="h-5 w-[72px] shrink-0" role="img" aria-label={`${label ?? fp.model}: ${reading.summary}`} data-testid="faceplate-mini">
      <rect x={1} y={1} width={70} height={18} rx={6} fill="var(--surface)" stroke="var(--border)" />
      {leds.map((l, i) => <LedDot key={l.id} x={xs[i] ?? 0} y={10} state={reading.leds[l.id] ?? "unknown"} tone={toneOf(l.role)} r={4} />)}
    </svg>
  );
}

/** Cartão de detalhe: painel + frase honesta + (opcional) números de óptica já coletados + legenda. */
export function FaceplateCard({ model, reported, serial, optics }: { model: string | null | undefined; reported: Reported; serial?: string; optics?: { rx: number | null; tx: number | null } }) {
  const fp = faceplateFor(model);
  const reading = readLeds(fp, reported);
  const generic = fp.model === "Painel genérico";
  return (
    <section aria-label="Painel frontal do equipamento" className="panel p-5" data-testid="faceplate-card">
      <div className="mb-4">
        <h2 className="text-sm font-semibold">Painel frontal · {fp.model}</h2>
        <p className="mt-0.5 text-xs text-muted">{fp.vendor} · {fp.form}</p>
      </div>
      <div className="sm:hidden"><Faceplate model={model} reported={reported} label={serial ?? fp.model} compact /><p className="mt-2 text-xs text-muted">Portas: {fp.ports.map((p) => p.label).join(" · ")}.</p></div>
      <div className="hidden sm:block"><Faceplate model={model} reported={reported} label={serial ?? fp.model} /></div>
      <p role="status" className="mt-3 text-sm">{reading.summary}</p>
      {generic && <p className="mt-2 text-xs text-muted">Modelo sem painel catalogado ou sem roteador vinculado: o desenho é neutro.</p>}
      {reading.lastKnown && <p className="mt-2 rounded-btn bg-stale-soft px-3 py-2 text-xs text-muted">Painel esvaziado pela idade do dado. Isso não significa que o equipamento esteja desligado ou sem sinal.</p>}
      {optics && (
        <div className="mt-4 border-t border-line pt-4">
          <dl className="grid grid-cols-2 gap-4">
            <div><dt className="text-xs text-muted">Rx (dBm)</dt><dd className="tabular mt-1 text-lg font-semibold">{optics.rx ?? "—"}</dd></div>
            <div><dt className="text-xs text-muted">Tx (dBm)</dt><dd className="tabular mt-1 text-lg font-semibold">{optics.tx ?? "—"}</dd></div>
          </dl>
          <p className="mt-2 text-xs text-muted">Sem limiar homologado: por isso sem cor de severidade.</p>
        </div>
      )}
      <div className="mt-5 border-t border-line pt-4"><FaceplateLegend model={model} reported={reported} /></div>
      <p className="mt-4 text-xs text-muted">{fp.source}. O estado dos LEDs é derivado do que a OLT reportou, não lido do equipamento.</p>
    </section>
  );
}
