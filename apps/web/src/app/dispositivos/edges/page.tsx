import { AppShell } from "@/components/AppShell";
import { DevicesTabs } from "@/components/DevicesTabs";
import { EmptyState, ErrorState, Kpi, PageHeader } from "@/components/ui";
import { apiSafe } from "@/lib/api";
import { EDGE_STATUS } from "@/lib/devices";
import type { EdgeRow } from "@/lib/types";

const ago = (iso: string | null) => {
  if (!iso) return "nunca";
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  return s < 90 ? "agora há pouco" : s < 5400 ? `há ${Math.round(s / 60)} min` : s < 172800 ? `há ${Math.round(s / 3600)} h` : `há ${Math.round(s / 86400)} d`;
};
const dot: Record<string, string> = { online: "●", offline: "▲", unknown: "○", revoked: "■" };
const tone: Record<string, string> = { online: "bg-ok-soft text-ok", offline: "bg-danger-soft text-danger", unknown: "bg-stale-soft text-muted", revoked: "bg-stale-soft text-muted" };

export default async function Edges() {
  const r = await apiSafe<EdgeRow[]>("/v1/edges");
  if (r.status === 403) return <AppShell active="/rede" user="1"><ErrorState title="Sem permissão" hint="Seu papel não permite ver os Edges." /></AppShell>;
  const edges = r.data ?? [];
  const versions = new Set(edges.map((e) => e.version).filter(Boolean));
  return (
    <AppShell active="/rede" user="1">
      <PageHeader title="Edges" subtitle="Os agentes que coletam e executam dentro da rede do provedor (somente leitura)" helpSlug="rede/edges" />
      <DevicesTabs current="/dispositivos/edges" />
      {r.data === null ? <ErrorState title="Falha ao carregar os Edges" /> : edges.length === 0 ? <EmptyState title="Nenhum Edge registrado" hint="Registre um Edge para começar a coletar." /> : (
        <div data-testid="edges-ready">
          <div className="mb-6 grid gap-3 sm:grid-cols-3">
            <Kpi label="Edges" value={edges.length} />
            <Kpi label="Online" value={edges.filter((e) => e.status === "online").length} hint="Batimento recente" />
            <Kpi label="Versões em uso" value={versions.size} hint={versions.size > 1 ? "Mais de uma versão: confira a coluna Versão" : "Todos na mesma versão"} />
          </div>
          <div className="panel overflow-x-auto">
            <table className="w-full min-w-[620px] text-sm">
              <caption className="sr-only">Edges do provedor</caption>
              <thead className="text-left text-muted"><tr>
                <th scope="col" className="p-3 font-medium">Nome</th><th scope="col" className="p-3 font-medium">Site</th><th scope="col" className="p-3 font-medium">Versão</th>
                <th scope="col" className="p-3 font-medium">Estado</th><th scope="col" className="p-3 font-medium">Último batimento</th>
              </tr></thead>
              <tbody className="divide-y divide-line">
                {edges.map((e) => (
                  <tr key={e.id}>
                    <td className="p-3 font-medium">{e.name}</td>
                    <td className="p-3">{e.site_name ?? "—"}</td>
                    <td className="p-3 font-mono text-xs">{e.version ?? "—"}</td>
                    <td className="p-3"><span className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium ${tone[e.status] ?? tone.unknown}`}><span aria-hidden>{dot[e.status] ?? "○"}</span>{EDGE_STATUS[e.status] ?? e.status}</span></td>
                    <td className="p-3 text-muted" title={e.last_heartbeat_at ?? undefined}>{ago(e.last_heartbeat_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-xs text-muted">“Sem sinal do Edge” não diz que a rede caiu: o Edge pode estar parado ou sem conexão com a nuvem. Os dados dele ficam marcados como defasados.</p>
        </div>
      )}
    </AppShell>
  );
}
