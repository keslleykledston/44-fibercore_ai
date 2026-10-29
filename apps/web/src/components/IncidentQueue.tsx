"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { EntityDetailDrawer } from "@/components/EntityDetailDrawer";
import { StatusPill } from "@/components/ui";
import type { Impact, Incident, IncidentDetail } from "@/lib/types";

const cause: Record<string, string> = { fiber_or_los: "Suspeita: perda de sinal / fibra", power: "Suspeita: falta de energia", unknown: "Causa não determinada" };
const ago = (iso: string) => { const m = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 60000)); return m < 90 ? `há ${m} min` : `há ${Math.round(m / 60)} h`; };

export function ImpactText({ i }: { i: Impact }) {
  if (i.hidden) return <>Impacto indisponível para o seu papel</>;
  if (i.customers_affected === null) return <>Impacto desconhecido (incidente sem ONUs registradas)</>;
  return <>{i.customers_affected} cliente(s) afetado(s) · fonte: associações aprovadas</>;
}

type Load = { state: "idle" } | { state: "loading" } | { state: "error"; msg: string } | { state: "ok"; d: IncidentDetail };

/** Fila de incidentes na ordem de prioridade do servidor; o incidente abre em painel lateral (sem trocar de tela). Só leitura. */
type Ack = { state: "idle" } | { state: "sending" } | { state: "error"; msg: string };

export function IncidentQueue({ incidents }: { incidents: Incident[] }) {
  const router = useRouter();
  const [sel, setSel] = useState<Incident | null>(null);
  const [acked, setAcked] = useState<Set<string>>(new Set());
  const [ack, setAck] = useState<Ack>({ state: "idle" });
  const [load, setLoad] = useState<Load>({ state: "idle" });
  const trigger = useRef<HTMLElement | null>(null);
  const close = () => { setSel(null); setLoad({ state: "idle" }); setAck({ state: "idle" }); trigger.current?.focus(); };
  const isAcked = (i: Incident) => i.acknowledged || acked.has(i.id);
  const reconhecer = async (id: string) => {
    setAck({ state: "sending" });
    try {
      const r = await fetch(`/bff/incidents/${id}/ack`, { method: "POST", cache: "no-store" });
      if (r.ok || r.status === 409) { // 409: outra pessoa já reconheceu; o estado final é o mesmo
        setAcked((s) => new Set(s).add(id)); setAck({ state: "idle" }); router.refresh(); // atualiza os indicadores do servidor
      } else setAck({ state: "error", msg: r.status === 403 ? "Seu papel não permite reconhecer incidentes." : "Não foi possível reconhecer o incidente. Tente de novo." });
    } catch { setAck({ state: "error", msg: "Não foi possível reconhecer o incidente. Tente de novo." }); }
  };
  const open = async (i: Incident, el: HTMLElement) => {
    trigger.current = el; setSel(i); setLoad({ state: "loading" });
    try {
      const r = await fetch(`/bff/incidents/${i.id}`, { cache: "no-store" });
      setLoad(r.ok ? { state: "ok", d: (await r.json()) as IncidentDetail } : { state: "error", msg: r.status === 403 ? "Seu papel não permite ver este incidente." : "Não foi possível carregar o incidente." });
    } catch { setLoad({ state: "error", msg: "Não foi possível carregar o incidente." }); }
  };
  return (
    <>
      <ul className="grid gap-3">
        {incidents.map((i) => (
          <li key={i.id} className="panel p-4" data-testid="incident-item">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="font-medium"><button type="button" data-testid="incident-open" aria-haspopup="dialog" className="min-h-touch text-left text-accent underline-offset-4 hover:underline" onClick={(e) => open(i, e.currentTarget)}>{i.olt} · PON {i.evidence.pon_path}</button></h2>
              <StatusPill value={i.status} />
            </div>
            <p className="mt-1 text-sm">{i.evidence.onus_down} de {i.evidence.onus_observed} ONUs fora ({Math.round((i.evidence.ratio ?? 0) * 100)}%) · LOS {i.evidence.los} · sem energia {i.evidence.dying_gasp}</p>
            <p className="text-sm" data-testid="incident-impact"><ImpactText i={i.impact} /></p>
            <p className="text-sm text-muted">{cause[i.suspected_cause] ?? cause.unknown} — hipótese, não diagnóstico.</p>
            {i.edge_silent && <p className="mt-1 text-sm text-warn">Edge silencioso: este é o último estado conhecido, não confirmado agora.</p>}
            <p className="mt-1 text-xs text-muted">{isAcked(i) ? "Reconhecido" : "Não reconhecido"}</p>
          </li>
        ))}
      </ul>
      <EntityDetailDrawer open={sel !== null} onClose={close} title={sel ? `${sel.olt} · PON ${sel.evidence.pon_path}` : "Incidente"}>
        {load.state === "loading" && <p role="status" className="text-sm text-muted">Carregando…</p>}
        {load.state === "error" && <p role="alert" className="text-sm text-danger">{load.msg}</p>}
        {load.state === "ok" && (
          <div className="space-y-4 text-sm" data-testid="incident-detail">
            <p><StatusPill value={load.d.status} /> <span className="text-muted">aberto {ago(load.d.opened_at)}</span></p>
            {load.d.edge_silent && <p className="text-warn">Edge silencioso: último estado conhecido, não confirmado agora.</p>}
            <dl className="space-y-1">
              <div className="flex justify-between gap-2"><dt className="text-muted">ONUs fora / observadas</dt><dd>{load.d.evidence.onus_down} / {load.d.evidence.onus_observed}</dd></div>
              <div className="flex justify-between gap-2"><dt className="text-muted">LOS · sem energia</dt><dd>{load.d.evidence.los} · {load.d.evidence.dying_gasp}</dd></div>
              <div className="flex justify-between gap-2"><dt className="text-muted">Cronicamente fora (não contam)</dt><dd>{load.d.evidence.chronic_offline ?? 0}</dd></div>
            </dl>
            <p data-testid="drawer-impact"><strong><ImpactText i={load.d.impact} /></strong></p>
            <p className="text-muted">{cause[load.d.suspected_cause] ?? cause.unknown} — hipótese, não diagnóstico. Nenhuma ação na rede é feita aqui.</p>
            {load.d.status === "open" && (
              <div data-testid="incident-ack">
                {isAcked(load.d) ? <p className="font-medium" data-testid="ack-done">Reconhecido</p> : (
                  <button type="button" disabled={ack.state === "sending"} onClick={() => reconhecer(load.d.id)} data-testid="ack-button"
                    className="min-h-touch rounded-btn border border-line bg-surface-2 px-4 font-medium hover:bg-accent-soft disabled:opacity-60">
                    {ack.state === "sending" ? "Reconhecendo…" : "Reconhecer incidente"}
                  </button>
                )}
                <p className="mt-1 text-xs text-muted">Registra que alguém assumiu a análise. Não altera nada na rede.</p>
                {ack.state === "error" && <p role="alert" className="mt-1 text-sm text-danger">{ack.msg}</p>}
              </div>
            )}
            <div>
              <h3 className="mb-1 font-medium">ONUs do incidente ({load.d.members_total})</h3>
              {load.d.members.length === 0 ? <p className="text-muted">Sem ONUs registradas neste incidente.</p> : (
                <ul className="divide-y divide-line rounded-btn border border-line">
                  {load.d.members.map((m) => <li key={m.id} className="flex items-center justify-between gap-2 px-3 py-2"><Link href={`/rede/onu/${m.id}`} className="min-h-touch font-mono text-accent underline-offset-4 hover:underline">{m.serial}</Link><StatusPill value={m.status} /></li>)}
                </ul>
              )}
              {load.d.members_truncated && <p className="mt-1 text-xs text-warn">Mostrando {load.d.members.length} de {load.d.members_total} ONUs.</p>}
            </div>
          </div>
        )}
      </EntityDetailDrawer>
    </>
  );
}
