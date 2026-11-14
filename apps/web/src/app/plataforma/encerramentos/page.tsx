import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { AdminTabs } from "@/components/AdminTabs";
import { AppShell } from "@/components/AppShell";
import { EmptyState, ErrorState, PageHeader } from "@/components/ui";
import { apiSafe } from "@/lib/api";
import { CLOSURE_STATE, type ClosureList, rowsDeleted } from "@/lib/platform";
import { platformStatus } from "@/lib/platformStatus";

const when = (iso: string) => new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short", timeZone: "America/Sao_Paulo" });

/** Registro permanente dos encerramentos (ADR-0050 D4): inclui organizações que já não existem. Só nome, motivo, datas e contagem de linhas apagadas; nenhum dado de pessoa. */
export default async function Encerramentos() {
  const status = await platformStatus();
  if (!status.operator) notFound();
  if (!status.mfa_recent) redirect("/plataforma/organizacoes");
  const r = await apiSafe<ClosureList>("/v1/platform/closures");
  if (r.status === 403) { if (r.detail === "mfa_recent_required") redirect("/plataforma/organizacoes"); notFound(); }
  const items = r.data?.items ?? [];
  return (
    <AppShell active="/administracao/modulos" user="1">
      <PageHeader title="Encerramentos" subtitle="Registro permanente de pedidos e encerramentos de organizações. Só a conta operadora vê esta tela." helpSlug="administracao/organizacoes">
        <Link href="/plataforma/organizacoes" data-testid="org-voltar" className="inline-flex min-h-touch items-center rounded-btn px-3 text-sm text-accent hover:underline">← Organizações</Link>
      </PageHeader>
      <AdminTabs current="/plataforma/organizacoes" />
      {r.data === null ? <ErrorState title="Falha ao carregar os encerramentos" hint="Tente de novo em instantes." /> : items.length === 0 ? <EmptyState title="Nenhum encerramento registrado" /> : (
        <section aria-label="Encerramentos" className="panel overflow-x-auto" data-testid="enc-lista">
          <table className="w-full min-w-[960px] text-sm">
            <caption className="sr-only">Encerramentos de organizações: nome, estado, motivo, pedido, carência, data do encerramento e linhas apagadas</caption>
            <thead className="text-left text-muted"><tr>
              <th scope="col" className="p-3 font-medium">Organização</th><th scope="col" className="p-3 font-medium">Estado</th><th scope="col" className="p-3 font-medium">Motivo</th>
              <th scope="col" className="p-3 font-medium">Pedido</th><th scope="col" className="p-3 font-medium">Carência até</th><th scope="col" className="p-3 font-medium">Encerrada</th>
              <th scope="col" className="p-3 text-right font-medium">Linhas apagadas</th>
            </tr></thead>
            <tbody className="divide-y divide-line">
              {items.map((c) => (
                <tr key={`${c.tenant_id}-${c.requested_at}`} data-testid="enc-linha">
                  <th scope="row" className="p-3 text-left font-medium">{c.name}</th>
                  <td className="p-3" data-testid="enc-estado">{CLOSURE_STATE[c.state] ?? c.state}</td>
                  <td className="p-3">{c.reason}</td>
                  <td className="p-3"><time dateTime={c.requested_at}>{when(c.requested_at)}</time></td>
                  <td className="p-3"><time dateTime={c.earliest_close_at}>{when(c.earliest_close_at)}</time></td>
                  <td className="p-3">{c.closed_at ? <time dateTime={c.closed_at}>{when(c.closed_at)}</time> : "—"}</td>
                  <td className="tabular p-3 text-right">{c.state === "closed" ? rowsDeleted(c.deleted_rows) : "—"}</td>
                </tr>))}
            </tbody>
          </table>
        </section>
      )}
      <p className="mt-2 text-xs text-muted">Este registro sobrevive ao apagamento da organização: não tem dado de cliente final, só o que ficou combinado. A trilha de auditoria da organização é apagada com ela (vai no arquivo exportado).</p>
    </AppShell>
  );
}

export const dynamic = "force-dynamic";
