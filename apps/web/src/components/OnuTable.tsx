"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { EntityDetailDrawer } from "@/components/EntityDetailDrawer";
import { DataFreshness, StatusPill } from "@/components/ui";
import type { Onu } from "@/lib/types";

/** Tabela de ONUs: o serial abre o resumo (painel lateral); de lá segue-se para a ONU 360 completa. */
export function OnuTable({ onus, oltNames }: { onus: Onu[]; oltNames: Record<string, string> }) {
  const [sel, setSel] = useState<Onu | null>(null);
  const trigger = useRef<HTMLElement | null>(null);
  const close = () => { setSel(null); trigger.current?.focus(); };
  return (
    <>
      <div className="panel overflow-x-auto">
        <table className="w-full min-w-[560px] text-sm">
          <thead className="text-left text-muted"><tr><th className="p-3 font-medium">Serial</th><th className="p-3 font-medium">OLT / PON</th><th className="p-3 font-medium">Status</th><th className="p-3 font-medium">Rx (dBm)</th><th className="p-3 font-medium">Dado</th></tr></thead>
          <tbody className="divide-y divide-line">
            {onus.map((u) => (
              <tr key={u.id}>
                <td className="p-3 font-mono">
                  <button type="button" data-testid="onu-open" aria-haspopup="dialog" className="min-h-touch rounded-btn text-left font-mono text-accent underline-offset-4 hover:underline"
                    onClick={(e) => { trigger.current = e.currentTarget; setSel(u); }}>{u.serial}</button>
                </td>
                <td className="p-3">{oltNames[u.olt_id] ?? "—"} · {u.pon_path ?? "—"}</td>
                <td className="p-3"><StatusPill value={u.status} /></td>
                <td className="p-3">{u.rx_dbm ?? "—"}</td>
                <td className="p-3"><DataFreshness freshness={u.freshness} observedAt={u.observed_at} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <EntityDetailDrawer open={sel !== null} onClose={close} title={sel ? `ONU ${sel.serial}` : "ONU"}>
        {sel && (
          <dl className="space-y-3 text-sm" data-testid="onu-summary">
            <div><dt className="text-muted">Status</dt><dd className="mt-1"><StatusPill value={sel.status} /></dd></div>
            <div><dt className="text-muted">OLT / PON</dt><dd>{oltNames[sel.olt_id] ?? "—"} · {sel.pon_path ?? "—"}</dd></div>
            <div><dt className="text-muted">Potência recebida (Rx)</dt><dd>{sel.rx_dbm !== null ? `${sel.rx_dbm} dBm` : "—"}</dd></div>
            <div><dt className="text-muted">Dado</dt><dd><DataFreshness freshness={sel.freshness} observedAt={sel.observed_at} /></dd></div>
            <Link href={`/rede/onu/${sel.id}`} data-testid="onu-360-link" className="mt-2 inline-flex min-h-touch items-center rounded-btn bg-accent px-4 font-medium text-white">Abrir ONU 360</Link>
          </dl>
        )}
      </EntityDetailDrawer>
    </>
  );
}
