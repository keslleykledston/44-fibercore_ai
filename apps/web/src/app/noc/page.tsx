import { AppShell } from "@/components/AppShell";
import { DataFreshness, EmptyState, ErrorState, PageHeader, StatusPill } from "@/components/ui";
import { apiSafe } from "@/lib/api";
import type { IncidentList } from "@/lib/types";

const cause: Record<string, string> = { fiber_or_los: "Suspeita: perda de sinal / fibra", power: "Suspeita: falta de energia", unknown: "Causa não determinada" };

export default async function Noc() {
  const r = await apiSafe<IncidentList>("/v1/incidents?limit=50");
  if (r.status === 403) return <AppShell active="/noc" user="1"><ErrorState title="Sem permissão" hint="Seu papel não permite ver incidentes." /></AppShell>;
  const list = r.data?.incidents ?? [];
  return (
    <AppShell active="/noc" user="1">
      <PageHeader title="NOC" subtitle="Quedas em massa por PON, com evidências" helpSlug="noc/acompanhar-incidente" />
      {(r.data?.alerts ?? []).map((a) => (
        <div key={a.edge} role="status" className="panel mb-3 border-warn p-4 text-sm" data-testid="edge-silent">
          <strong>Edge {a.edge} sem dados</strong> <DataFreshness freshness="stale" observedAt={a.last_heartbeat_at} />
          <p className="text-muted">Os estados atrás deste edge são o último conhecido; não indicam que as ONUs estão offline.</p>
        </div>
      ))}
      <div data-testid="incident-queue">
        {r.data === null ? <ErrorState title="Falha ao carregar incidentes" /> : list.length === 0 ? <EmptyState title="Nenhum incidente" /> : (
          <ul className="grid gap-3">
            {list.map((i) => (
              <li key={i.id} className="panel p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h2 className="font-medium">{i.olt} · PON {i.evidence.pon_path}</h2>
                  <StatusPill value={i.status} />
                </div>
                <p className="mt-1 text-sm">{i.evidence.onus_down} de {i.evidence.onus_observed} ONUs fora ({Math.round((i.evidence.ratio ?? 0) * 100)}%) · LOS {i.evidence.los} · sem energia {i.evidence.dying_gasp}</p>
                <p className="text-sm text-muted">{cause[i.suspected_cause] ?? cause.unknown} — hipótese, não diagnóstico.</p>
                {i.edge_silent && <p className="mt-1 text-sm text-warn">Edge silencioso: este é o último estado conhecido, não confirmado agora.</p>}
                <p className="mt-1 text-xs text-muted">{i.acknowledged ? "Reconhecido" : "Não reconhecido"}</p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </AppShell>
  );
}
