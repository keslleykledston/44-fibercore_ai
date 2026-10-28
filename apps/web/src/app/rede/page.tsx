import { AppShell } from "@/components/AppShell";
import { DataFreshness, EmptyState, ErrorState, PageHeader, StatusPill } from "@/components/ui";
import { apiSafe } from "@/lib/api";
import type { Olt, Onu } from "@/lib/types";

export default async function Rede({ searchParams }: { searchParams: Promise<{ serial?: string }> }) {
  const { serial } = await searchParams;
  const q = serial && /^[A-Za-z0-9._-]{1,64}$/.test(serial) ? `&serial=${encodeURIComponent(serial.toUpperCase())}` : "";
  const [olts, onus] = await Promise.all([apiSafe<Olt[]>("/v1/olts?limit=200"), apiSafe<Onu[]>(`/v1/onus?limit=200${q}`)]);
  if (olts.status === 403 || onus.status === 403) return <AppShell active="/rede" user="1"><ErrorState title="Sem permissão" hint="Seu papel não permite ver o inventário." /></AppShell>;
  const byId = new Map((olts.data ?? []).map((o) => [o.id, o]));
  return (
    <AppShell active="/rede" user="1">
      <PageHeader title="Rede" subtitle="OLTs e ONUs com frescor e fonte do dado" helpSlug="rede/consultar-onu" />
      <div data-testid="onu-inventory-ready" className="grid gap-6 lg:grid-cols-[320px_1fr]">
        <section aria-label="OLTs">
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">OLTs</h2>
          {olts.data === null ? <ErrorState title="Falha ao carregar OLTs" /> : olts.data.length === 0 ? <EmptyState title="Nenhuma OLT coletada" hint="Aguarde a primeira coleta do Edge." /> : (
            <ul className="panel divide-y divide-line">
              {olts.data.map((o) => (
                <li key={o.id} className="p-3">
                  <div className="font-medium">{o.name}</div>
                  <div className="text-sm text-muted">{o.vendor} {o.model ?? ""} · {o.onu_count} ONUs</div>
                  <div className="mt-1 flex items-center gap-3"><StatusPill value={o.support_level} /><DataFreshness freshness={o.freshness} observedAt={o.observed_at} /></div>
                </li>
              ))}
            </ul>
          )}
        </section>
        <section aria-label="ONUs" className="min-w-0">
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">ONUs{serial ? ` · busca “${serial}”` : ""}</h2>
          {onus.data === null ? <ErrorState title="Falha ao carregar ONUs" /> : onus.data.length === 0 ? <EmptyState title="Nenhuma ONU encontrada" hint={serial ? "Confira o serial informado." : undefined} /> : (
            <div className="panel overflow-x-auto">
              <table className="w-full min-w-[560px] text-sm">
                <thead className="text-left text-muted"><tr><th className="p-3 font-medium">Serial</th><th className="p-3 font-medium">OLT / PON</th><th className="p-3 font-medium">Status</th><th className="p-3 font-medium">Rx (dBm)</th><th className="p-3 font-medium">Dado</th></tr></thead>
                <tbody className="divide-y divide-line">
                  {onus.data.map((u) => (
                    <tr key={u.id}>
                      <td className="p-3 font-mono">{u.serial}</td>
                      <td className="p-3">{byId.get(u.olt_id)?.name ?? "—"} · {u.pon_path ?? "—"}</td>
                      <td className="p-3"><StatusPill value={u.status} /></td>
                      <td className="p-3">{u.rx_dbm ?? "—"}</td>
                      <td className="p-3"><DataFreshness freshness={u.freshness} observedAt={u.observed_at} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </AppShell>
  );
}
