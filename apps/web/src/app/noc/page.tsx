import { AppShell } from "@/components/AppShell";
import { IncidentQueue } from "@/components/IncidentQueue";
import { DataFreshness, EmptyState, ErrorState, Kpi, PageHeader } from "@/components/ui";
import { apiSafe } from "@/lib/api";
import type { IncidentList } from "@/lib/types";

export default async function Noc({ searchParams }: { searchParams: Promise<{ f?: string }> }) {
  const { f } = await searchParams;
  const onlyUnack = f === "nao-reconhecidos";
  // A ordem de prioridade é do servidor (uma só fonte): abertos, não reconhecidos, queda confirmada antes de edge silencioso, maior impacto, mais ONUs fora.
  const r = await apiSafe<IncidentList>("/v1/incidents?limit=50&order=priority");
  if (r.status === 403) return <AppShell active="/noc" user="1"><ErrorState title="Sem permissão" hint="Seu papel não permite ver incidentes." /></AppShell>;
  const all = r.data?.incidents ?? [];
  const list = onlyUnack ? all.filter((i) => i.status === "open" && !i.acknowledged) : all;
  const s = r.data?.summary;
  return (
    <AppShell active="/noc" user="1">
      <PageHeader title="NOC" subtitle="Quedas em massa por PON, priorizadas, com impacto e evidências" helpSlug="noc/acompanhar-incidente" />
      {s && (
        <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="noc-kpis">
          <Kpi label="Incidentes abertos" value={s.open} hint={s.open_suppressed > 0 ? `${s.open_suppressed} atrás de Edge silencioso (último estado conhecido)` : undefined} />
          <Kpi label="Não reconhecidos" value={s.unacknowledged} />
          <Kpi label="Clientes afetados" value={s.customers_hidden ? "—" : (s.customers_affected ?? "—")} hint={s.customers_hidden ? "Indisponível para o seu papel" : "Distintos, via associações aprovadas; não inclui Edge silencioso"} />
          <Kpi label="Edges silenciosos" value={s.silent_edges} hint="Não contam como ONUs offline" />
        </div>
      )}
      {(r.data?.alerts ?? []).map((a) => (
        <div key={a.edge} role="status" className="panel mb-3 border-warn p-4 text-sm" data-testid="edge-silent">
          <strong>Edge {a.edge} sem dados</strong> <DataFreshness freshness="stale" observedAt={a.last_heartbeat_at} />
          <p className="text-muted">Os estados atrás deste edge são o último conhecido; não indicam que as ONUs estão offline.</p>
        </div>
      ))}
      <nav aria-label="Filtro da fila" className="mb-3 flex gap-2 text-sm">
        <a href="/noc" aria-current={!onlyUnack ? "page" : undefined} className={`inline-flex min-h-touch items-center rounded-btn px-3 ${!onlyUnack ? "bg-accent-soft font-medium text-accent" : "text-muted hover:underline"}`}>Todos</a>
        <a href="/noc?f=nao-reconhecidos" aria-current={onlyUnack ? "page" : undefined} data-testid="filter-unack" className={`inline-flex min-h-touch items-center rounded-btn px-3 ${onlyUnack ? "bg-accent-soft font-medium text-accent" : "text-muted hover:underline"}`}>Só não reconhecidos</a>
      </nav>
      {s && all.filter((i) => i.status === "open").length < s.open && (
        <p role="status" className="mb-2 text-sm text-warn" data-testid="queue-cut">Mostrando {all.filter((i) => i.status === "open").length} dos {s.open} incidentes abertos, os de maior prioridade.{r.data?.truncated ? " Há mais do que a fila consegue ordenar." : ""}</p>
      )}
      <div data-testid="incident-queue">
        {r.data === null ? <ErrorState title="Falha ao carregar incidentes" /> : list.length === 0 ? <EmptyState title={onlyUnack ? "Nenhum incidente não reconhecido" : "Nenhum incidente"} /> : <IncidentQueue incidents={list} />}
      </div>
    </AppShell>
  );
}
