"use client";

import Link from "next/link";
import { useEffect, useId, useRef, useState } from "react";
import { ledLabel, type Led, type OltPanelModel, type PortModel, type SlotModel } from "@/lib/oltPanel";

/** Painel frontal VETORIAL da Huawei MA5608T (pacote FiberCore-MA5608T v1.0, geometria adaptada ao tema do FiberCore). Só leitura: nunca consulta a OLT, não tem comando.
 *  Cada PON é um botão (mouse, toque, Enter/Espaço); o popover mostra o estado da PORTA e, separado, as ONUs UP/DOWN. A cor do LED nunca é o único indicador:
 *  o rótulo acessível, o popover e a legenda dizem o estado em texto. Esquemático, não é planta de fabricante: a área de controle/uplink é só ilustração. */
const LED_FILL: Record<Led, string> = { up: "#22c55e", down: "#ef4444", warning: "#f59e0b", disabled: "#64748b", unknown: "#94a3b8" };
const SLOT_Y: Record<number, number> = { 0: 89, 1: 171 };
const portX = (i: number, cap: number) => (cap === 16 ? 433 + i * 53 + (i >= 8 ? 12 : 0) : 433 + i * 106);

function Screw({ x, y }: { x: number; y: number }) {
  return <g aria-hidden><circle cx={x} cy={y} r="8" fill="#27303d" stroke="#64748b" strokeWidth="1.5" /><path d={`M${x - 3} ${y - 3}l6 6M${x + 3} ${y - 3}l-6 6`} stroke="#9aabbf" strokeWidth="1.5" /></g>;
}

function Pon({ p, cap, y, onSelect, active }: { p: PortModel; cap: number; y: number; onSelect: (p: PortModel, el: Element) => void; active: boolean }) {
  const x = portX(p.port, cap);
  const label = `PON ${p.key}: ${ledLabel(p.led)}. ONUs UP ${p.onus.online ?? "sem leitura"}, DOWN ${p.onus.offline ?? "sem leitura"}`;
  const fire = (el: Element) => onSelect(p, el);
  return (
    <g id={`slot-${p.slot}-pon-${String(p.port).padStart(2, "0")}`} data-testid="olt-pon" data-port-key={p.key} data-led={p.led} role="button" tabIndex={0} aria-label={label} aria-pressed={active}
      className="fc-pon" style={{ cursor: "pointer", outline: "none" }}
      onClick={(e) => fire(e.currentTarget)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fire(e.currentTarget); } }}>
      <text x={x + 11} y={y - 3} textAnchor="middle" fill="#405269" fontSize="10" fontWeight="600">{p.port}</text>
      <rect className="fc-pon-body" x={x} y={y + 2} width="22" height="24" rx="3" fill="#687b8c" stroke={active ? "#38bdf8" : "#3c4b5e"} strokeWidth={active ? 2.6 : 1} />
      <rect x={x + 3} y={y + 5} width="16" height="18" rx="2" fill="#121d2b" stroke="#172d41" />
      <rect x={x + 5} y={y + 8} width="12" height="12" rx="1" fill="#08131f" stroke="#526473" strokeWidth=".7" />
      <circle cx={x + 11} cy={y + 14} r="3.3" fill="#161b22" stroke="#9aa9b8" />
      <rect x={x + 7} y={y + 19} width="8" height="2" rx="1" fill="#677987" />
      <circle cx={x + 11} cy={y + 31} r="3.3" fill={LED_FILL[p.led]} stroke="#f8fafc" strokeWidth=".8" />
      {p.led === "warning" && <path d={`M${x + 11} ${y + 28.5}v3.4`} stroke="#1e293b" strokeWidth="1.2" />}
      {p.led === "unknown" && <circle cx={x + 11} cy={y + 31} r="1.1" fill="#475569" />}
      <title>{label}</title>
    </g>
  );
}

function Slot({ s, faceId, onSelect, activeKey }: { s: SlotModel; faceId: string; onSelect: (p: PortModel, el: Element) => void; activeKey: string | null }) {
  const y = SLOT_Y[s.slot] ?? 89;
  const title = s.supported ? `${s.boardModel} • ${s.ponCapacity}P` : s.presence === "empty" ? "SEM PLACA" : s.presence === "present" ? (s.boardModel ? "CARTÃO SEM TEMPLATE" : "PLACA NÃO LIDA") : "SEM DADOS";
  const body = s.supported ? null : s.presence === "empty" ? "SLOT VAZIO (confirmado pelo inventário)" : s.presence === "present" ? "CARTÃO SEM TEMPLATE VALIDADO" : "INVENTÁRIO NÃO LIDO (não é slot vazio)";
  return (
    <g id={`slot-${s.slot}-group`} data-testid="olt-slot" data-slot={s.slot} data-presence={s.presence} data-supported={s.supported ? "true" : "false"}>
      <rect x="237" y={y} width="1097" height="80" rx="5" fill={`url(#${faceId})`} stroke="#7c8997" />
      <rect x="246" y={y + 12} width="154" height="55" rx="4" fill="#dbe1e9" stroke="#a9b7c5" />
      <rect x="254" y={y + 16} width="65" height="20" rx="3" fill="#2d4054" />
      <text x="286" y={y + 30} textAnchor="middle" fontSize="11" fill="white" fontWeight="700">SLOT {s.slot}</text>
      <text x="255" y={y + 58} fontSize="11" fontWeight="700" fill="#243449">{title}</text>
      <circle cx="341" cy={y + 23} r="4" fill={s.presence === "present" ? "#22c55e" : "#94a3b8"} />
      <text x="350" y={y + 27} fontSize="9" fill="#5c6b78">{s.presence === "present" ? "RUN" : "—"}</text>
      <rect x="411" y={y + 6} width="886" height="67" rx="3" fill={s.supported ? "#eef2f7" : "#cdd5df"} stroke="#c6d0db" />
      {s.supported ? s.ports.map((p) => <Pon key={p.key} p={p} cap={s.ponCapacity!} y={y + 26} onSelect={onSelect} active={activeKey === p.key} />)
        : <text x="837" y={y + 43} textAnchor="middle" fontSize="14" fontWeight="700" fill="#758395">{body}</text>}
      <Screw x={242} y={y + 40} /><Screw x={1326} y={y + 40} />
    </g>
  );
}

function Control({ faceId }: { faceId: string }) {
  return (
    <g id="control-boards" aria-hidden>
      <rect x="237" y="254" width="1097" height="67" rx="5" fill={`url(#${faceId})`} stroke="#778699" />
      <rect x="248" y="262" width="140" height="51" rx="4" fill="#dbe1e9" stroke="#a9b7c5" />
      <text x="254" y="281" fontSize="11" fill="#2d4054" fontWeight="700">CTRL 2/3</text>
      <text x="254" y="300" fontSize="11" fill="#526579">UPLINK / MGMT (ilustrativo)</text>
      {[420, 750].map((base) => <g key={base}><text x={base} y="271" fontSize="10" fill="#526579">GE/10GE</text>
        {Array.from({ length: 6 }, (_, i) => <g key={i}><rect x={base + i * 42} y="282" width="30" height="28" rx="2" fill="#526476" /><rect x={base + i * 42 + 4} y="286" width="22" height="19" rx="2" fill="#08131f" /></g>)}</g>)}
      <rect x="1126" y="263" width="187" height="49" rx="4" fill="#dbe1e9" stroke="#adbcc9" /><text x="1138" y="279" fontSize="10" fill="#526579">ENERGIA</text>
      {[1140, 1220].map((x) => <rect key={x} x={x} y="286" width="70" height="20" rx="3" fill="#3d4a5c" />)}
    </g>
  );
}

const LEGEND: { led: Led; text: string }[] = [
  { led: "up", text: "UP — porta operacional e nenhuma ONU fora" }, { led: "warning", text: "ATENÇÃO — ONU(s) fora (a porta pode estar UP)" },
  { led: "down", text: "DOWN — a OLT informou a porta DOWN" }, { led: "disabled", text: "Desabilitada" }, { led: "unknown", text: "Sem leitura" },
];

export function OltPanel({ oltId, oltName, model, panel }: { oltId: string; oltName: string; model: string; panel: OltPanelModel }) {
  const faceId = useId().replace(/:/g, "");
  const wrap = useRef<HTMLDivElement>(null);
  const closeBtn = useRef<HTMLButtonElement>(null);
  const opener = useRef<Element | null>(null);
  const [sel, setSel] = useState<{ key: string; x: number; y: number } | null>(null);
  const port = sel ? panel.slots.flatMap((s) => s.ports).find((p) => p.key === sel.key) ?? null : null;   // sempre o valor MAIS NOVO do painel, nunca uma cópia do clique
  const close = () => { setSel(null); (opener.current as HTMLElement | null)?.focus?.(); };
  const select = (p: PortModel, el: Element) => {
    const w = wrap.current; if (!w) return;
    const r = w.getBoundingClientRect(), s = el.getBoundingClientRect();
    opener.current = el;
    setSel({ key: p.key, x: Math.max(8, Math.min(s.left - r.left - 100, r.width - 288)), y: Math.max(8, Math.min(s.bottom - r.top + 10, r.height - 230)) });
  };
  useEffect(() => { if (sel) closeBtn.current?.focus(); }, [sel?.key]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!sel) return;
    const away = (e: PointerEvent) => { const t = e.target as Element; if (!t.closest?.(".fc-pon-popover") && !t.closest?.(".fc-pon")) setSel(null); };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [sel]);
  const n = (v: number | null) => (v === null ? "—" : v);
  const ago = panel.boardsObservedAt ? new Date(panel.boardsObservedAt).toLocaleString("pt-BR") : null;
  return (
    <details open className="panel mb-4 p-4" data-testid="olt-panel">
      <summary className="cursor-pointer text-sm font-semibold">Painel da OLT · {model}</summary>
      <p className="mt-1 text-xs text-muted" data-testid="olt-panel-note">
        Vista esquemática de {oltName}. O LED mostra o estado da <strong>porta</strong>; as <strong>ONUs</strong> UP/DOWN aparecem no detalhe ao clicar.
        {panel.boardsDemo ? " DEMONSTRAÇÃO: inventário de placas SINTÉTICO, não vem de equipamento." : ago ? ` Inventário de placas lido em ${ago}${panel.boardsStale ? " (desatualizado)" : ""}.` : " Inventário de placas ainda não lido: cartão desconhecido não é slot vazio."}
        {panel.dataQuality === "stale" ? " Dados de ONU desatualizados: nada é afirmado." : panel.dataQuality === "partial" ? " Leitura de ONUs parcial." : ""}
      </p>
      <div ref={wrap} className="relative mt-3" onKeyDown={(e) => { if (e.key === "Escape" && sel) { e.stopPropagation(); close(); } }}>
        <svg viewBox="0 0 1440 386" role="group" aria-label={`Painel frontal da OLT ${oltName}, slots de serviço 0 e 1`} className="block h-auto w-full" data-testid="olt-svg">
          <defs><linearGradient id={faceId} x1="0" y1="0" x2="0" y2="1"><stop stopColor="#f5f7fa" /><stop offset="1" stopColor="#bdc7d3" /></linearGradient></defs>
          <g fontFamily="Inter, system-ui, sans-serif">
            <rect x="29" y="65" width="1382" height="258" rx="12" fill="#293340" />
            <path d="M75 65 L1370 65 L1320 18 L130 18 Z" fill="#445266" stroke="#1e293b" strokeWidth="2" />
            {[14, 1377].map((x) => <g key={x} aria-hidden><rect x={x} y="92" width="49" height="231" rx="8" fill="#384659" />{[112, 296].map((yy) => <circle key={yy} cx={x + 24} cy={yy} r="8" fill="#e7edf2" />)}</g>)}
            <g aria-hidden><rect x="66" y="85" width="165" height="237" rx="4" fill={`url(#${faceId})`} /><text x="85" y="118" fontSize="22" fontWeight="800" fill="#b91c1c">HUAWEI</text>
              <text x="85" y="140" fontSize="18" fontWeight="800" fill="#1e293b">{model}</text><text x="85" y="162" fontSize="10" fill="#536579">FAN / SYS</text></g>
            {panel.slots.map((s) => <Slot key={s.slot} s={s} faceId={faceId} onSelect={select} activeKey={sel?.key ?? null} />)}
            <Control faceId={faceId} />
          </g>
        </svg>
        {sel && port && (
          <section role="dialog" aria-modal="false" aria-label={`Detalhes da PON ${port.key}`} data-testid="olt-popover" data-led={port.led}
            className="fc-pon-popover absolute z-20 w-[270px] max-w-[calc(100vw-2rem)] rounded-btn border border-line bg-surface p-3 text-sm shadow-lg" style={{ left: sel.x, top: sel.y }}>
            <div className="mb-2 flex items-center justify-between gap-2">
              <strong className="text-xs">{oltName} · PON {port.key}</strong>
              <button ref={closeBtn} type="button" onClick={close} aria-label="Fechar detalhes da PON" className="min-h-touch min-w-touch rounded-btn px-2 text-lg leading-none hover:bg-bg">×</button>
            </div>
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 border-t border-line pt-2 text-xs">
              <dt className="text-muted">Estado da porta</dt><dd className="text-right font-semibold" data-testid="olt-popover-operational">{port.operational === "up" ? "UP" : port.operational === "down" ? "DOWN" : "não lido"}{port.operationalSource === "onu_online" ? " (por ONU online)" : ""}</dd>
              <dt className="text-muted">Condição</dt><dd className="text-right font-semibold" data-testid="olt-popover-condition">{ledLabel(port.led)}</dd>
            </dl>
            <div className="my-2 grid grid-cols-2 gap-2">
              <div className="rounded-btn border border-line p-2"><small className="block text-[10px] text-muted">ONUs UP</small><b className="tabular text-xl" style={{ color: "var(--ok)" }} data-testid="olt-popover-up">{n(port.onus.online)}</b></div>
              <div className="rounded-btn border border-line p-2"><small className="block text-[10px] text-muted">ONUs DOWN</small><b className="tabular text-xl" style={{ color: "var(--danger)" }} data-testid="olt-popover-down">{n(port.onus.offline)}</b></div>
            </div>
            <p className="text-[11px] text-muted">Provisionadas lidas: {n(port.onus.total)} · Qualidade: {port.quality === "fresh" ? "atual" : port.quality === "stale" ? "desatualizada" : port.quality === "partial" ? "parcial" : "indisponível"}</p>
            {port.note && <p className="mt-1 text-[11px] text-muted" data-testid="olt-popover-note">{port.note}</p>}
            <Link href={`/rede?olt=${encodeURIComponent(oltId)}&pon=${encodeURIComponent(port.key)}`} className="mt-2 inline-flex min-h-touch items-center text-xs text-accent underline underline-offset-2">Ver as ONUs desta PON</Link>
          </section>
        )}
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted" aria-label="Legenda dos LEDs">
        {LEGEND.map((l) => <li key={l.led} className="flex items-center gap-1.5"><span aria-hidden className="inline-block size-2.5 rounded-full border border-line" style={{ background: LED_FILL[l.led] }} />{l.text}</li>)}
      </ul>
    </details>
  );
}
