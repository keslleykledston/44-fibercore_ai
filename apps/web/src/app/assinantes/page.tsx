import { AppShell } from "@/components/AppShell";
import { EmptyState, ErrorState, PageHeader } from "@/components/ui";
import Link from "next/link";
import { apiSafe } from "@/lib/api";
import { featureOn } from "@/lib/features";
import type { Association, CustomerRow } from "@/lib/types";

const n = (v: string | undefined) => (v && /^\d{1,5}$/.test(v) ? v : "0");

export default async function Assinantes({ searchParams }: { searchParams: Promise<Record<string, string | undefined>> }) {
  const q = await searchParams;
  const PAGE = 50;
  const page = Math.max(1, Math.min(10_000, Number(/^\d{1,5}$/.test(q.p ?? "") ? q.p : 1)));
  // pede 1 item a mais para saber se há próxima página (nenhum vínculo fica inacessível)
  const r = await apiSafe<Association[]>(`/v1/associations?status=suggested&limit=${PAGE + 1}&offset=${(page - 1) * PAGE}`);
  if (r.status === 403) return <AppShell active="/assinantes" user="1"><ErrorState title="Sem permissão" hint="Seu papel não permite ver assinantes." /></AppShell>;
  const sub360 = await featureOn("subscriber_360");
  // clientes: busca por nome (q) e páginas de 20; pede 1 a mais para saber se há próxima (nenhum cliente fica inacessível)
  const CPAGE = 20;
  const cq = (q.q ?? "").trim().slice(0, 64);
  const cpage = Math.max(1, Math.min(10_000, Number(/^\d{1,5}$/.test(q.c ?? "") ? q.c : 1)));
  const customers = sub360
    ? await apiSafe<CustomerRow[]>(`/v1/customers?limit=${CPAGE + 1}&offset=${(cpage - 1) * CPAGE}${cq ? `&q=${encodeURIComponent(cq)}` : ""}`)
    : null;
  const cMore = (customers?.data ?? []).length > CPAGE;
  const cList = (customers?.data ?? []).slice(0, CPAGE);
  const cHref = (n: number) => `/assinantes?c=${n}${cq ? `&q=${encodeURIComponent(cq)}` : ""}`;
  const hasMore = (r.data ?? []).length > PAGE;
  const list = (r.data ?? []).slice(0, PAGE);
  return (
    <AppShell active="/assinantes" user="1">
      <PageHeader title="Assinantes" subtitle="Importe clientes e revise os vínculos sugeridos entre ONU e cliente" helpSlug="assinantes/importar-e-revisar-vinculos" />
      {q.ok === "import" && <p role="status" data-testid="import-report" className="panel mb-4 p-4 text-sm">Importação concluída: {n(q.a)} aceitas, {n(q.r)} rejeitadas, {n(q.s)} sugestões ({n(q.c)} com conflito). Os valores das linhas rejeitadas não são exibidos.</p>}
      {(q.ok === "approve" || q.ok === "reject") && <p role="status" className="panel mb-4 p-4 text-sm">Vínculo {q.ok === "approve" ? "aprovado" : "rejeitado"}.</p>}
      {q.erro && <p role="alert" className="panel mb-4 border-danger p-4 text-sm text-danger">Não foi possível concluir a operação ({q.erro === "409" ? "o vínculo já foi revisado, é ambíguo ou a ONU já tem vínculo aprovado" : q.erro === "403" ? "sem permissão" : "erro " + q.erro.slice(0, 8)}).</p>}
      <div className="grid gap-6 lg:grid-cols-[320px_1fr]">
        <div className="grid content-start gap-6">
        <section aria-label="Importar CSV">
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">Importar CSV</h2>
          <form action="/bff/erp/import" method="post" encType="multipart/form-data" className="panel grid gap-3 p-4" data-testid="import-form">
            <label className="grid gap-1 text-sm">Origem
              <input name="source" defaultValue="csv-manual" pattern="[a-z0-9][a-z0-9_.-]{1,39}" required className="min-h-touch rounded-btn border border-line bg-bg px-3" />
            </label>
            <label className="grid gap-1 text-sm">Arquivo (UTF-8, até 2 MiB)
              <input name="file" type="file" accept=".csv,text/csv" required className="min-h-touch rounded-btn border border-line bg-bg p-2 text-sm" />
            </label>
            <p className="text-xs text-muted">Colunas: erp_customer_id, display_name; opcionais: document, contract_status, onu_serial.</p>
            <button type="submit" className="min-h-touch rounded-btn bg-accent px-4 font-medium text-[color:var(--on-accent)]">Importar</button>
          </form>
        </section>
        {customers && (
          <section aria-label="Clientes" data-testid="customer-list">
            <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">Clientes · visão 360</h2>
            <form action="/assinantes" method="get" role="search" className="mb-2 flex gap-2">
              <label className="sr-only" htmlFor="cq">Buscar cliente pelo nome</label>
              <input id="cq" name="q" defaultValue={cq} maxLength={64} placeholder="Buscar cliente pelo nome" className="min-h-touch min-w-0 flex-1 rounded-btn border border-line bg-bg px-3 text-sm" />
              <button className="min-h-touch rounded-btn border border-line px-3 text-sm">Buscar</button>
            </form>
            {customers.data === null ? <ErrorState title="Falha ao carregar clientes" /> : cList.length === 0 ? <EmptyState title={cq ? "Nenhum cliente com esse nome" : "Nenhum cliente importado"} /> : (
              <ul className="panel divide-y divide-line">
                {cList.map((c) => <li key={c.id}><Link href={`/assinantes/${c.id}`} className="flex min-h-touch items-center justify-between gap-2 px-3 py-2 text-sm hover:bg-accent-soft"><span>{c.display_name}</span><span className="text-xs text-accent">Ver 360 →</span></Link></li>)}
              </ul>
            )}
            {(cpage > 1 || cMore) && (
              <nav aria-label="Paginação de clientes" className="mt-2 flex items-center justify-between text-sm" data-testid="customer-pagination">
                {cpage > 1 ? <a className="min-h-touch rounded-btn border border-line px-3 py-2" href={cHref(cpage - 1)}>← Anteriores</a> : <span />}
                <span className="text-muted">Página {cpage}</span>
                {cMore ? <a className="min-h-touch rounded-btn border border-line px-3 py-2" href={cHref(cpage + 1)}>Próximos →</a> : <span />}
              </nav>
            )}
          </section>
        )}
        </div>
        <section aria-label="Vínculos sugeridos" className="min-w-0">
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">Vínculos sugeridos</h2>
          {r.data === null ? <ErrorState title="Falha ao carregar vínculos" /> : list.length === 0 ? <EmptyState title="Nenhum vínculo para revisar" hint="Importe um CSV com a coluna onu_serial." /> : (
            <ul className="panel divide-y divide-line" data-testid="association-list">
              {list.map((a) => {
                const blocked = a.evidence.ambiguous_serial === true;
                return (
                  <li key={a.id} className="grid gap-2 p-4">
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <span><span className="font-mono">{a.onu_serial}</span> → <strong>{a.customer_name}</strong></span>
                      <span className="text-sm text-muted">Pontuação {a.score}/100</span>
                    </div>
                    <p className="text-sm text-muted">Evidência: serial idêntico{blocked ? " · serial presente em mais de uma OLT (ambíguo: resolva o inventário antes de aprovar)" : ""}{a.evidence.conflicts_with_approved ? " · conflita com um vínculo já aprovado" : ""}.</p>
                    <div className="flex flex-wrap gap-2">
                      <details>
                        <summary className={`inline-flex min-h-touch cursor-pointer items-center rounded-btn border border-line px-3 text-sm ${blocked ? "pointer-events-none opacity-50" : ""}`} aria-disabled={blocked}>Aprovar</summary>
                        <form action={`/bff/associations/${a.id}/approve`} method="post" className="mt-2 flex items-center gap-2 text-sm">
                          <span>Confirmar vínculo?</span><button className="min-h-touch rounded-btn bg-accent px-3 text-[color:var(--on-accent)]">Confirmar aprovação</button>
                        </form>
                      </details>
                      <details>
                        <summary className="inline-flex min-h-touch cursor-pointer items-center rounded-btn border border-line px-3 text-sm">Rejeitar</summary>
                        <form action={`/bff/associations/${a.id}/reject`} method="post" className="mt-2 flex items-center gap-2 text-sm">
                          <span>Rejeitar sugestão?</span><button className="min-h-touch rounded-btn border border-line px-3">Confirmar rejeição</button>
                        </form>
                      </details>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
          {(page > 1 || hasMore) && (
            <nav aria-label="Paginação" className="mt-3 flex items-center justify-between text-sm" data-testid="pagination">
              {page > 1 ? <a className="min-h-touch rounded-btn border border-line px-3 py-2" href={`/assinantes?p=${page - 1}`}>← Anteriores</a> : <span />}
              <span className="text-muted">Página {page}{hasMore ? " · há mais sugestões" : ""}</span>
              {hasMore ? <a className="min-h-touch rounded-btn border border-line px-3 py-2" href={`/assinantes?p=${page + 1}`}>Próximas →</a> : <span />}
            </nav>
          )}
        </section>
      </div>
    </AppShell>
  );
}
