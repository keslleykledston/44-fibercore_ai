import Link from "next/link";
import { DevicesTabs } from "@/components/DevicesTabs";
import { AppShell } from "@/components/AppShell";
import { DataFreshness, EmptyState, ErrorState, Kpi, PageHeader, StatusPill } from "@/components/ui";
import { apiSafe } from "@/lib/api";
import { BASIS, humanHours, offlineQuery, parseOfflineFilters } from "@/lib/offline";
import type { Olt, OfflineOnuReport } from "@/lib/types";

type Q = { min_hours?: string; olt_id?: string; pon_path?: string; include_stale?: string };

export default async function OnusOffline({ searchParams }: { searchParams: Promise<Q> }) {
  const f = parseOfflineFilters(await searchParams);
  const [rep, olts] = await Promise.all([apiSafe<OfflineOnuReport>(`/v1/onus/offline?${offlineQuery(f, { limit: "500" })}`), apiSafe<Olt[]>("/v1/olts?limit=200")]);
  if (rep.status === 403) return <AppShell active="/rede" user="1"><ErrorState title="Sem permissão" hint="Seu papel não permite ver o inventário." /></AppShell>;
  const csv = `/bff/onus/offline?${offlineQuery(f)}`;
  return (
    <AppShell active="/rede" user="1">
      <PageHeader title="ONUs offline" subtitle="Quem está fora do ar há mais tempo, com a base de cada horário" helpSlug="rede/onus-offline">
        <Link href="/rede" className="inline-flex min-h-touch items-center rounded-btn px-3 text-sm text-accent underline-offset-4 hover:underline">Voltar à Rede</Link>
      </PageHeader>
      <DevicesTabs current="/rede/offline" />
      <form method="get" role="search" aria-label="Filtros" className="panel mb-6 grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-[140px_1fr_160px_auto_auto] lg:items-end">
        <label className="text-sm">Fora do ar há pelo menos (horas)
          <input name="min_hours" type="number" min={0} max={8760} step="any" defaultValue={f.minHours} className="mt-1 min-h-touch w-full rounded-btn border border-line bg-bg px-3" />
        </label>
        <label className="text-sm">OLT
          <select name="olt_id" defaultValue={f.oltId ?? ""} className="mt-1 min-h-touch w-full rounded-btn border border-line bg-bg px-3">
            <option value="">Todas</option>
            {(olts.data ?? []).map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
          </select>
        </label>
        <label className="text-sm">PON (ex.: 0/0/14)
          <input name="pon_path" defaultValue={f.ponPath ?? ""} pattern="[0-9/]{1,32}" className="mt-1 min-h-touch w-full rounded-btn border border-line bg-bg px-3 font-mono" />
        </label>
        <label className="flex min-h-touch items-center gap-2 text-sm"><input type="checkbox" name="include_stale" value="1" defaultChecked={f.includeStale} />Incluir dados defasados</label>
        <button type="submit" className="min-h-touch rounded-btn bg-accent px-4 font-medium text-[color:var(--on-accent)]">Filtrar</button>
      </form>
      {rep.data === null ? <ErrorState title="Falha ao carregar o relatório" /> : (
        <div data-testid="offline-report-ready">
          <div className="mb-6 grid gap-3 sm:grid-cols-3">
            <Kpi label="Listadas" value={rep.data.count} hint={rep.data.truncated ? "Lista cortada em 500: refine os filtros ou baixe o CSV" : `há ${f.minHours} h ou mais`} />
            <Kpi label="Sem horário de início" value={rep.data.excluded.unknown_start} hint="Fora do ar sem nenhuma queda registrada nem horário da OLT; não entram na lista" />
            <Kpi label="Dados defasados" value={rep.data.excluded.stale} hint={f.includeStale ? "Incluídas na lista" : "Deixadas de fora (OLT sem coleta recente)"} />
          </div>
          <div className="mb-3 flex justify-end"><a href={csv} data-testid="offline-csv" className="inline-flex min-h-touch items-center rounded-btn border border-line px-4 text-sm hover:bg-surface-2">Baixar CSV</a></div>
          {rep.data.items.length === 0 ? <EmptyState title="Nenhuma ONU encontrada com esses filtros" hint="Diminua as horas ou inclua dados defasados." /> : (
            <div className="panel overflow-x-auto">
              <table className="w-full min-w-[720px] text-sm">
                <caption className="sr-only">ONUs fora do ar, as mais antigas primeiro</caption>
                <thead className="text-left text-muted"><tr>
                  <th scope="col" className="p-3 font-medium">Serial</th><th scope="col" className="p-3 font-medium">OLT / PON</th><th scope="col" className="p-3 font-medium">Estado</th>
                  <th scope="col" className="p-3 font-medium">Fora do ar há</th><th scope="col" className="p-3 font-medium">Desde / visto online</th><th scope="col" className="p-3 font-medium">Base do horário</th><th scope="col" className="p-3 font-medium">Últimos 30 dias</th><th scope="col" className="p-3 font-medium">Dado</th>
                </tr></thead>
                <tbody className="divide-y divide-line">
                  {rep.data.items.map((i) => (
                    <tr key={i.onu_id}>
                      <td className="p-3 font-mono"><Link href={`/rede/onu/${i.onu_id}`} className="text-accent underline-offset-4 hover:underline">{i.serial}</Link></td>
                      <td className="p-3">{i.olt} · {i.pon_path ?? "—"}</td>
                      <td className="p-3"><StatusPill value={i.status} /></td>
                      <td className="tabular p-3 font-medium">{i.basis === "since_last_online" ? "até " : ""}{humanHours(i.offline_hours)}</td>
                      <td className="tabular p-3" data-testid="offline-since">{i.basis === "since_last_online" && <span className="text-muted">Visto online em </span>}<time dateTime={i.offline_since}>{new Date(i.offline_since).toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo" })}</time></td>
                      <td className="p-3" title={BASIS[i.basis].hint}>{BASIS[i.basis].label}<span className="sr-only">. {BASIS[i.basis].hint}</span></td>
                      <td className="tabular p-3" data-testid="offline-30d">{i.drops_30d ?? 0} {(i.drops_30d ?? 0) === 1 ? "queda" : "quedas"}<span className="block text-xs text-muted">{humanHours(i.offline_hours_30d ?? 0)} fora do ar</span></td>
                      <td className="p-3"><DataFreshness freshness={i.freshness} observedAt={i.observed_at} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="mt-3 text-xs text-muted">“No máximo” = a ONU foi vista online pela última vez nesse horário; a queda pode ser mais recente. “Informado pela OLT” usa o relógio da OLT, que pode divergir alguns minutos.</p>
        </div>
      )}
    </AppShell>
  );
}
