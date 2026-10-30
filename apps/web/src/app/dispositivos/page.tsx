import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { DevicesTabs } from "@/components/DevicesTabs";
import { DataFreshness, EmptyState, ErrorState, Kpi, PageHeader } from "@/components/ui";
import { apiSafe } from "@/lib/api";
import { distinct, filterCpes, parseCpeFilters, protocolLabel } from "@/lib/devices";
import type { Cpe } from "@/lib/types";

type Q = { q?: string; vendor?: string; model?: string; protocol?: string; freshness?: string };
const LIMIT = 1000;

export default async function Dispositivos({ searchParams }: { searchParams: Promise<Q> }) {
  const f = parseCpeFilters(await searchParams);
  const r = await apiSafe<Cpe[]>(`/v1/cpes?limit=${LIMIT}`);
  if (r.status === 403) return <AppShell active="/rede" user="1"><ErrorState title="Sem permissão" hint="Seu papel não permite ver o inventário." /></AppShell>;
  const all = r.data ?? [];
  const shown = filterCpes(all, f);
  const stale = all.filter((c) => c.freshness !== "fresh").length;
  const sel = "mt-1 min-h-touch w-full rounded-btn border border-line bg-bg px-3";
  return (
    <AppShell active="/rede" user="1">
      <PageHeader title="Dispositivos" subtitle="CPEs coletados pelo GenieACS, com fonte, protocolo e idade do dado (somente leitura)" helpSlug="rede/dispositivos" />
      <DevicesTabs current="/dispositivos" />
      {r.data === null ? <ErrorState title="Falha ao carregar os CPEs" /> : (
        <div data-testid="cpe-list-ready">
          <div className="mb-6 grid gap-3 sm:grid-cols-3">
            <Kpi label="CPEs" value={all.length} hint={all.length >= LIMIT ? `Mostrando os primeiros ${LIMIT}` : "No inventário do provedor"} />
            <Kpi label="Fabricantes" value={distinct(all.map((c) => c.vendor)).length} />
            <Kpi label="Dados defasados" value={stale} hint="Sem coleta recente: é a idade do dado, não que o CPE caiu" />
          </div>
          <form method="get" role="search" aria-label="Filtros" className="panel mb-4 grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-[1fr_1fr_1fr_1fr_1fr_auto] lg:items-end">
            <label className="text-sm">Serial ou ID no ACS<input name="q" defaultValue={f.q} maxLength={64} className={`${sel} font-mono`} /></label>
            <label className="text-sm">Fabricante
              <select name="vendor" defaultValue={f.vendor} className={sel}><option value="">Todos</option>{distinct(all.map((c) => c.vendor)).map((v) => <option key={v}>{v}</option>)}</select></label>
            <label className="text-sm">Modelo
              <select name="model" defaultValue={f.model} className={sel}><option value="">Todos</option>{distinct(all.map((c) => c.model)).map((v) => <option key={v}>{v}</option>)}</select></label>
            <label className="text-sm">Protocolo
              <select name="protocol" defaultValue={f.protocol} className={sel}><option value="">Todos</option>{distinct(all.flatMap((c) => c.bindings.map((b) => b.protocol))).map((v) => <option key={v} value={v}>{protocolLabel(v)}</option>)}</select></label>
            <label className="text-sm">Dado
              <select name="freshness" defaultValue={f.freshness} className={sel}><option value="">Todos</option><option value="fresh">Atualizado</option><option value="stale">Defasado</option><option value="unknown">Sem coleta</option></select></label>
            <button type="submit" className="min-h-touch rounded-btn bg-accent px-4 font-medium text-[color:var(--on-accent)]">Filtrar</button>
          </form>
          {shown.length === 0 ? <EmptyState title="Nenhum CPE com esses filtros" hint={all.length === 0 ? "Aguarde a primeira coleta do GenieACS pelo Edge." : "Limpe os filtros."} /> : (
            <div className="panel overflow-x-auto">
              <table className="w-full min-w-[720px] text-sm">
                <caption className="sr-only">CPEs do provedor</caption>
                <thead className="text-left text-muted"><tr>
                  <th scope="col" className="p-3 font-medium">Serial</th><th scope="col" className="p-3 font-medium">Fabricante / modelo</th><th scope="col" className="p-3 font-medium">Firmware</th>
                  <th scope="col" className="p-3 font-medium">Protocolo</th><th scope="col" className="p-3 font-medium">Dado</th>
                </tr></thead>
                <tbody className="divide-y divide-line">
                  {shown.map((c) => (
                    <tr key={c.id}>
                      <td className="p-3 font-mono"><Link href={`/dispositivos/${c.id}`} className="text-accent underline-offset-4 hover:underline">{c.canonical_serial}</Link></td>
                      <td className="p-3">{c.vendor ?? "—"} · {c.model ?? "—"}</td>
                      <td className="p-3 font-mono text-xs">{c.firmware ?? "—"}</td>
                      <td className="p-3">{c.bindings.length ? c.bindings.map((b) => protocolLabel(b.protocol)).join(", ") : "—"}</td>
                      <td className="p-3"><DataFreshness freshness={c.freshness} observedAt={c.observed_at} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </AppShell>
  );
}
