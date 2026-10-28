import Link from "next/link";
import { redirect } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { DataFreshness, EmptyState, ErrorState, Kpi, PageHeader, StatusPill } from "@/components/ui";
import { api, apiSafe } from "@/lib/api";
import { getSession } from "@/lib/session";
import type { Edge, IncidentList, Olt, Onu, Workspace } from "@/lib/types";

export default async function Overview() {
  const { token, workspace } = await getSession();
  if (!token) redirect("/login");
  const inc = await apiSafe<IncidentList>("/v1/incidents?status=open&limit=3");
  if (inc.status === 400 || (!workspace && inc.status === 404)) return <WorkspacePicker />;
  if (inc.status === 403) return <Forbidden />;
  const [onus, olts, edges] = await Promise.all([
    apiSafe<Onu[]>("/v1/onus?limit=1000"), apiSafe<Olt[]>("/v1/olts?limit=200"), apiSafe<Edge[]>("/v1/edges"),
  ]);
  const onuList = onus.data ?? [];
  const stale = onuList.filter((o) => o.freshness !== "fresh").length;
  const down = onuList.filter((o) => ["offline", "los", "dying_gasp"].includes(o.status) && o.freshness === "fresh").length;
  const online = onuList.filter((o) => o.status === "online" && o.freshness === "fresh").length;
  const silent = (edges.data ?? []).filter((e) => e.status === "offline").length;
  const queue = inc.data?.incidents ?? [];
  return (
    <AppShell active="/" user="1">
      <PageHeader title="Visão Geral" subtitle="Estado da rede e prioridades de hoje" helpSlug="visao-geral/visao-geral" />
      <section aria-label="Indicadores" className="grid grid-cols-2 gap-3 md:grid-cols-4" data-testid="kpis">
        <Kpi label="ONUs online" value={online} />
        <Kpi label="ONUs fora" value={down} hint="apenas dados atualizados" />
        <Kpi label="Dados defasados" value={stale} hint="último estado conhecido" />
        <Kpi label="Edges silenciosos" value={silent} />
      </section>
      <section aria-label="Incidentes prioritários" className="mt-8">
        <h2 className="mb-3 text-lg font-semibold">Incidentes prioritários</h2>
        {inc.data === null ? <ErrorState title="Não foi possível carregar incidentes" /> :
          queue.length === 0 ? <EmptyState title="Nenhum incidente aberto" hint="A rede observada está sem quedas em massa." /> : (
          <ul className="panel divide-y divide-line" data-testid="priority-incidents">
            {queue.map((i) => (
              <li key={i.id} className="flex items-center justify-between gap-3 p-4">
                <div>
                  <Link href="/noc" className="font-medium hover:underline">{i.olt} · PON {i.evidence.pon_path}</Link>
                  <div className="text-sm text-muted">{i.evidence.onus_down} de {i.evidence.onus_observed} ONUs fora{i.edge_silent ? " · edge silencioso (último estado conhecido)" : ""}</div>
                </div>
                <StatusPill value={i.status} />
              </li>
            ))}
          </ul>
        )}
        {(inc.data?.alerts ?? []).map((a) => (
          <p key={a.edge} className="mt-2 text-sm text-warn" role="status">Edge {a.edge} sem dados — estados atrás dele são o último conhecido, não offline.</p>
        ))}
      </section>
      <p className="mt-6 text-sm text-muted">{(olts.data ?? []).length} OLT(s) monitoradas. <DataFreshness freshness={(olts.data ?? [])[0]?.freshness} observedAt={(olts.data ?? [])[0]?.observed_at} /></p>
    </AppShell>
  );
}

async function WorkspacePicker() {
  const ws = await api<Workspace[]>("/v1/auth/workspaces");
  return (
    <main className="mx-auto grid min-h-screen max-w-sm content-center gap-4 px-4">
      <h1 className="text-2xl font-semibold">Escolha o workspace</h1>
      <form action="/bff/workspace" method="post" className="panel grid gap-2 p-4" data-testid="workspace-picker">
        {ws.map((w) => (
          <button key={w.tenant_id} name="workspace" value={w.tenant_id} className="min-h-touch rounded-btn border border-line px-3 text-left text-sm hover:bg-bg">
            {w.name} <span className="text-muted">· {w.role}</span>
          </button>
        ))}
        {ws.length === 0 && <EmptyState title="Você não pertence a nenhum workspace" />}
      </form>
    </main>
  );
}

function Forbidden() {
  return <AppShell active="/" user="1"><ErrorState title="Sem permissão" hint="Seu papel não permite ver esta área." /></AppShell>;
}
