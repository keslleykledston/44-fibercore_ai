import { AdminTabs } from "@/components/AdminTabs";
import { AppShell } from "@/components/AppShell";
import { ErrorState, PageHeader, StatusPill } from "@/components/ui";
import { apiSafe } from "@/lib/api";
import type { Mod } from "@/lib/types";

export default async function Modulos() {
  const r = await apiSafe<Mod[]>("/v1/platform/modules");
  return (
    <AppShell active="/administracao/modulos" user="1">
      <PageHeader title="Módulos" subtitle="Estado real por sondagem; módulo sem implementação aparece como desconhecido" helpSlug="administracao/saude-modulos" />
      <AdminTabs current="/administracao/modulos" />
      {r.data === null ? <ErrorState title="Falha ao carregar módulos" /> : (
        <div className="panel overflow-x-auto" data-testid="modules-table">
          <table className="w-full min-w-[560px] text-sm">
            <thead className="text-left text-muted"><tr><th className="p-3 font-medium">Módulo</th><th className="p-3 font-medium">Estado</th><th className="p-3 font-medium">Versão</th><th className="p-3 font-medium">Motivo</th></tr></thead>
            <tbody className="divide-y divide-line">
              {r.data.map((m) => (
                <tr key={m.id}><td className="p-3 font-medium">{m.id}</td><td className="p-3"><StatusPill value={m.status} /></td><td className="p-3">{m.version}</td><td className="p-3 text-muted">{m.reason}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </AppShell>
  );
}
