import Link from "next/link";
import { notFound } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { SourceChip } from "@/components/SourceChip";
import { EmptyState, ErrorState, PageHeader } from "@/components/ui";
import { apiSafe } from "@/lib/api";
import { diagnosticsOn } from "@/lib/features";
import { buildSteps, conclusion, readRd004, RUN_FRESH_MINUTES, TRUST_LABEL, ticketSummary, type Trust } from "@/lib/troubleshoot";
import type { CustomerContext, DiagnosticRun } from "@/lib/types";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const TONE: Record<Trust, string> = { confirmado: "bg-ok-soft text-ok", hipotese: "bg-warn-soft text-warn", indisponivel: "bg-stale-soft text-muted" };

function Badge({ t }: { t: Trust }) {
  const l = TRUST_LABEL[t];
  return <span data-testid={`trust-${t}`} className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium ${TONE[t]}`}><span aria-hidden>{l.icon}</span>{l.label}</span>;
}

export default async function GuidedTroubleshooting({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ onu?: string; run?: string; run4?: string; passo?: string; erro?: string }> }) {
  const { id } = await params;
  const q = await searchParams;
  if (!UUID.test(id) || !(await diagnosticsOn())) notFound();  // desligado = a tela não existe para este provedor
  const shell = (c: React.ReactNode) => <AppShell active="/assinantes" user="1">{c}</AppShell>;
  const r = await apiSafe<CustomerContext>(`/v1/customers/${id}/context`);
  if (r.status === 404) notFound();
  if (r.status === 403) return shell(<ErrorState title="Sem permissão (403)" hint="Seu papel não permite acessar este assinante. Nenhum dado pessoal ou de conexão é exibido." />);
  if (!r.data) return shell(<ErrorState title="Não foi possível carregar o diagnóstico" hint="Nenhuma informação sobre a conexão pode ser afirmada enquanto as fontes não responderem. Recarregue a página." />);
  const ctx = r.data;
  const onu = ctx.onus.find((x) => x.id === q.onu) ?? ctx.onus[0];
  // a execução só vale para ESTA ONU: um link antigo ou de outra ONU é ignorado (nunca mostra a PON errada)
  const run = onu && q.run && UUID.test(q.run) ? await apiSafe<DiagnosticRun>(`/v1/diagnostics/runs/${q.run}`) : null;
  const mine = run?.data && run.data.scope.onu_id === onu?.id && run.data.rule_id === "R-D001" ? run.data : null;
  const ageMin = mine ? (Date.now() - Date.parse(mine.created_at)) / 60000 : 0;
  const samePon = !!mine && !!onu?.pon_id && mine.scope.pon_id === onu.pon_id;  // identificador estável: o caminho (0/1/0) repete entre OLTs
  const discarded = !mine ? null : !samePon ? "other_pon" : ageMin > RUN_FRESH_MINUTES ? "old" : null;
  const valid = mine && !discarded ? mine : null;
  const denied = q.erro === "403";
  // R-D004 (sessão do roteador com o ACS): outra execução, outro parâmetro (`run4`); só vale para ESTA ONU e se recente, e o achado é lido em formato fechado
  const run4 = onu && q.run4 && UUID.test(q.run4) ? await apiSafe<DiagnosticRun>(`/v1/diagnostics/runs/${q.run4}`) : null;
  const mine4 = run4?.data && run4.data.scope.onu_id === onu?.id && run4.data.rule_id === "R-D004" ? run4.data : null;
  const age4 = mine4 ? (Date.now() - Date.parse(mine4.created_at)) / 60000 : 0;
  const old4 = !!mine4 && age4 > RUN_FRESH_MINUTES;
  const f4 = mine4 && !old4 ? readRd004(mine4) : null;
  const wrong4 = !!q.run4 && !mine4 ? "other_onu" as const : old4 ? "old" as const : null;
  const at = (iso: string, m: number) => `${new Date(iso).toISOString().replace("T", " ").slice(0, 16)} UTC (há ${Math.max(0, Math.round(m))} min)`;
  const steps = buildSteps(ctx, onu, { finding: valid?.findings[0] ?? null, denied, failed: !!q.erro && !denied && q.passo !== "6", discarded,
    ranAt: valid ? at(valid.created_at, ageMin) : null },
  { finding: f4, denied, failed: !!q.erro && !denied && q.passo === "6", discarded: wrong4, ranAt: f4 && mine4 ? at(mine4.created_at, age4) : null }, id, true);
  const concl = conclusion(steps);
  const cur = steps.find((s) => String(s.id) === q.passo) ?? steps[valid ? 3 : 0];
  const base = `/assinantes/diagnostico/${id}?${onu ? `onu=${onu.id}&` : ""}${valid ? `run=${valid.run_id}&` : ""}${f4 && mine4 ? `run4=${mine4.run_id}&` : ""}`;
  // o formulário de executar leva a regra do passo e a execução da OUTRA regra para a tela voltar com as duas
  const other = cur.id === 6 ? valid?.run_id : f4 && mine4 ? mine4.run_id : undefined;
  const runAction = onu ? `/bff/diagnostics/run/${id}/${onu.id}?rule=${cur.id === 6 ? "R-D004" : "R-D001"}${other ? `&keep=${other}` : ""}` : "";
  return shell(
    <>
      <PageHeader title={`Diagnóstico guiado · ${ctx.customer.display_name}`} subtitle="Passo a passo, somente leitura, com a confiança de cada passo" helpSlug="assinantes/diagnostico-guiado">
        <Link href={`/assinantes/${id}`} className="inline-flex min-h-touch items-center rounded-btn px-3 text-sm text-accent hover:underline">← Voltar para a Visão 360</Link>
      </PageHeader>
      <div data-testid="diag-ready" className="grid gap-4">
        <section aria-label="Conclusão" data-testid="diag-conclusion" className="panel p-4">
          <div className="flex flex-wrap items-center gap-3"><Badge t={concl.trust} /><h2 className="text-lg font-semibold">Conclusão</h2></div>
          <p className="mt-2 max-w-3xl text-sm">{concl.text}</p>
          {concl.trust === "hipotese" && <p className="mt-1 text-xs text-muted">Hipótese exige confirmação humana. Nenhuma alteração foi feita na rede.</p>}
        </section>
        {q.erro && <p role="alert" className="text-sm text-danger">{denied ? "Seu papel não permite executar o diagnóstico." : `Não foi possível executar o diagnóstico (erro ${q.erro.slice(0, 8)}).`}</p>}
        {!onu ? <EmptyState title="Nenhuma ONU aprovada para este cliente" hint="Aprove o vínculo em Assinantes para diagnosticar a conexão." /> : null}
        <div className="grid items-start gap-4 lg:grid-cols-[320px_1fr]">
          <nav aria-label="Passos do diagnóstico">
            <ol className="panel divide-y divide-line" data-testid="diag-steps">
              {steps.map((s) => (
                <li key={s.id}>
                  <a href={`${base}passo=${s.id}`} aria-current={s.id === cur.id ? "step" : undefined} data-testid={`step-${s.id}`}
                    className={`flex min-h-touch items-start justify-between gap-3 px-3 py-3 text-sm ${s.id === cur.id ? "bg-accent-soft" : "hover:bg-accent-soft"}`}>
                    <span><span className="text-muted">{s.id}.</span> {s.title}</span><Badge t={s.trust} />
                  </a>
                </li>
              ))}
            </ol>
          </nav>
          <section aria-label={`Passo ${cur.id}`} data-testid="diag-evidence" className="panel p-4">
            <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="text-sm font-semibold uppercase tracking-wide text-muted">{cur.id}. {cur.title}</h2><Badge t={cur.trust} /></div>
            <p className="mt-3 text-sm">{cur.summary}</p>
            {cur.facts.length > 0 && <dl className="mt-3">{cur.facts.map(([k, v]) => <div key={k} className="flex flex-wrap items-baseline justify-between gap-2 py-1 text-sm"><dt className="text-muted">{k}</dt><dd className="text-right">{v}</dd></div>)}</dl>}
            {cur.provenance && <div className="mt-2 text-right"><SourceChip p={cur.provenance} /></div>}
            {cur.action?.kind === "link" && <Link href={cur.action.href ?? "#"} data-testid="step-action" className="mt-4 inline-flex min-h-touch items-center text-sm text-accent underline underline-offset-2">{cur.action.label}</Link>}
            {cur.action?.kind === "run" && onu && (
              <form action={runAction} method="post" className="mt-4">
                <button data-testid="step-action" className="min-h-touch rounded-btn bg-accent px-4 text-sm font-medium text-[color:var(--on-accent)]">{cur.action.label}</button>
              </form>
            )}
          </section>
        </div>
        <details className="panel p-4" data-testid="ticket">
          <summary className="inline-flex min-h-touch cursor-pointer items-center rounded-btn border border-line px-3 text-sm">Gerar resumo para ticket</summary>
          <label htmlFor="ticket-text" className="mt-3 block text-xs text-muted">Texto para copiar. Não altera nada na rede.</label>
          <textarea id="ticket-text" readOnly rows={12} defaultValue={ticketSummary(ctx.customer.display_name, steps, concl, new Date())} className="mt-1 w-full rounded-btn border border-line bg-bg p-3 font-mono text-xs" />
        </details>
      </div>
    </>,
  );
}
