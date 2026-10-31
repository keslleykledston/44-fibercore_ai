"use client";

import { useMemo, useRef, useState, type ReactNode } from "react";
import { OnuQuickInspector } from "@/components/OnuQuickInspector";
import { rovingKeys } from "@/lib/roving";
import { DataFreshness, StatusPill } from "@/components/ui";
import type { Onu } from "@/lib/types";

type F = "todas" | "fora" | "defasado" | "desconhecido";
const DOWN = new Set(["offline", "los", "dying_gasp"]);
const MATCH: Record<F, (o: Onu) => boolean> = {
  todas: () => true,
  fora: (o) => DOWN.has(o.status),
  defasado: (o) => o.freshness !== "fresh",
  desconhecido: (o) => o.status === "unknown",
};
const LABEL: Record<F, string> = { todas: "Todas", fora: "Fora do ar", defasado: "Defasadas", desconhecido: "Desconhecido" };

/** Gestão de ONUs (ADR-0037, padrão Lovable): [árvore | lista com filtros | detalhes] lado a lado; a lista nunca fica atrás do painel. Largura < 1024: árvore em cima e detalhes em gaveta. */
export function OnuWorkspace({ onus, oltNames, tree, ontConfig = false }: { onus: Onu[]; oltNames: Record<string, string>; tree?: ReactNode; ontConfig?: boolean }) {
  const showOlt = !tree;   // com a árvore, a OLT é o contexto da página: a coluna mostra só a PON; na busca por serial (várias OLTs) mostra OLT · PON
  const [selId, setSelId] = useState<string | null>(null);
  const sel = useMemo(() => onus.find((o) => o.id === selId) ?? null, [onus, selId]);   // a seleção só vale enquanto a ONU ainda está no conjunto exibido
  const [f, setF] = useState<F>("todas");
  const [q, setQ] = useState("");
  const trigger = useRef<HTMLElement | null>(null);
  const close = () => { setSelId(null); trigger.current?.focus(); };
  const needle = q.trim().toLowerCase();
  const rows = useMemo(() => onus.filter((o) => MATCH[f](o) && (!needle || o.serial.toLowerCase().includes(needle))), [onus, f, needle]);
  const count = (k: F) => onus.filter(MATCH[k]).length;
  return (
    <div className={`grid items-start gap-4 ${tree ? "lg:grid-cols-[240px_minmax(0,1fr)_320px] 2xl:grid-cols-[240px_minmax(0,1fr)_380px]" : "lg:grid-cols-[minmax(0,1fr)_320px] 2xl:grid-cols-[minmax(0,1fr)_380px]"}`} data-testid="onu-table-quick">
      {tree}
      <div className="min-w-0">
        <div className="mb-3 flex flex-wrap items-center gap-2" data-testid="onu-filters">
          <input aria-label="Filtrar por serial" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filtrar por serial" maxLength={64}
            className="min-h-touch min-w-[11rem] flex-1 rounded-btn border border-line bg-surface px-3 text-sm sm:max-w-xs" />
          <div role="radiogroup" aria-label="Filtro por estado" className="flex flex-wrap gap-1 rounded-btn bg-surface-2 p-1">
            {(Object.keys(LABEL) as F[]).map((k, i, all) => (
              <button key={k} type="button" role="radio" aria-checked={f === k} tabIndex={f === k ? 0 : -1} onClick={() => setF(k)} onKeyDown={(e) => rovingKeys(e, i, all.length, (n) => setF(all[n]!))}
                className={`min-h-9 rounded-[8px] px-3 text-sm ${f === k ? "bg-surface font-medium shadow-card" : "text-muted hover:text-text"}`}>
                {LABEL[k]}<span className="tabular ml-1 text-xs text-muted">{count(k)}</span>
              </button>
            ))}
          </div>
          <p role="status" aria-live="polite" className="ml-auto text-sm text-muted" data-testid="onu-count">{rows.length === onus.length ? `${rows.length} ONUs` : `${rows.length} de ${onus.length} ONUs`}</p>
        </div>
        <div className="panel overflow-x-auto">
          <table className="w-full min-w-[560px] text-sm">
            <thead className="bg-surface-2 text-left text-xs text-muted"><tr><th className="px-4 py-2 font-medium">Serial</th><th className="px-4 py-2 font-medium">{showOlt ? "OLT / PON" : "PON"}</th><th className="px-4 py-2 font-medium">Status</th><th className="px-4 py-2 text-right font-medium">Rx (dBm)</th><th className="px-4 py-2 font-medium">Dado</th></tr></thead>
            <tbody className="divide-y divide-line">
              {rows.map((u) => (
                <tr key={u.id} aria-selected={sel?.id === u.id} className={`h-12 ${sel?.id === u.id ? "bg-accent-soft" : "hover:bg-surface-2"}`}>
                  <td className="px-4 font-mono">
                    <button type="button" data-testid="onu-open" aria-haspopup="true" aria-current={sel?.id === u.id ? "true" : undefined}
                      className="min-h-touch rounded-btn text-left font-mono text-accent underline-offset-4 hover:underline" onClick={(e) => { trigger.current = e.currentTarget; setSelId(u.id); }}>{u.serial}</button>
                  </td>
                  <td className="whitespace-nowrap px-4">{showOlt ? `${oltNames[u.olt_id] ?? "—"} · ` : ""}{u.pon_path ?? "—"}</td>
                  <td className="px-4"><StatusPill value={u.status} /></td>
                  <td className="tabular px-4 text-right">{u.rx_dbm ?? "—"}</td>
                  <td className="whitespace-nowrap px-4"><DataFreshness freshness={u.freshness} observedAt={u.observed_at} /></td>
                </tr>
              ))}
              {rows.length === 0 && <tr><td colSpan={5} className="p-4 text-sm text-muted">Nenhuma ONU com este filtro.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
      <OnuQuickInspector ontConfig={ontConfig} row={sel} oltName={sel ? oltNames[sel.olt_id] ?? "—" : "—"} onClose={close} />
    </div>
  );
}
