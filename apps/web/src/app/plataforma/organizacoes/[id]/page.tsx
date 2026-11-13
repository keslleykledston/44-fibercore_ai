import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { AdminTabs } from "@/components/AdminTabs";
import { AppShell } from "@/components/AppShell";
import { ErrorState, PageHeader } from "@/components/ui";
import { apiSafe } from "@/lib/api";
import { ACTION_LABEL, FEATURE_NOTES, FEATURE_STATE_LABEL, ORG_ERRORS, ORG_FLASH, ORG_STATUS, type PlatformOrgDetail, UUID_FORMAT, featureChoices, healthText, historyText } from "@/lib/platform";
import { platformStatus } from "@/lib/platformStatus";

const field = "min-h-touch rounded-btn border border-line bg-bg px-3";
const btn = "min-h-touch rounded-btn border border-line px-4 text-sm hover:bg-bg";
const when = (iso: string) => new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short", timeZone: "America/Sao_Paulo" });
type Search = { ok?: string | string[]; erro?: string | string[] };
const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v) ?? "";

/** Uma organização para o operador (ADR-0047 D2): estado, saúde, suspender/reativar, renomear, recursos e histórico. Só contagens e rótulos; nada de dado de assinante, OLT ou ONU. */
export default async function OrganizacaoDetalhe({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<Search> }) {
  const { id } = await params;
  const status = await platformStatus();
  if (!status.operator || !UUID_FORMAT.test(id)) notFound();
  if (!status.mfa_recent) redirect("/plataforma/organizacoes");              // o passo do segundo fator mora na lista
  const sp = await searchParams;
  const ok = one(sp.ok), erro = one(sp.erro);
  const r = await apiSafe<PlatformOrgDetail>(`/v1/platform/organizations/${id}`);
  if (r.status === 404) notFound();
  if (r.status === 403) { if (r.detail === "mfa_recent_required") redirect("/plataforma/organizacoes"); notFound(); }
  const o = r.data;
  return (
    <AppShell active="/administracao/modulos" user="1">
      <PageHeader title={o?.name ?? "Organização"} subtitle="Estado, recursos e histórico. Só a conta operadora vê esta tela." helpSlug="administracao/organizacoes">
        <Link href="/plataforma/organizacoes" data-testid="org-voltar" className="inline-flex min-h-touch items-center rounded-btn px-3 text-sm text-accent hover:underline">← Organizações</Link>
      </PageHeader>
      <AdminTabs current="/plataforma/organizacoes" />
      {erro && ORG_ERRORS[erro] && <p role="alert" data-testid="org-erro" className="mb-4 rounded-btn border border-danger px-3 py-2 text-sm text-danger">{ORG_ERRORS[erro]}</p>}
      {ok && ORG_FLASH[ok] && <p role="status" data-testid="org-flash" className="mb-4 rounded-btn border border-ok px-3 py-2 text-sm text-ok">{ORG_FLASH[ok]}</p>}
      {!o ? <ErrorState title="Falha ao carregar a organização" hint="Tente de novo em instantes." /> : (
        <div className="grid gap-4">
          <section aria-label="Resumo" className="panel p-4" data-testid="org-resumo">
            <dl className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-2 lg:grid-cols-4">
              <div><dt className="text-xs text-muted">Estado</dt><dd data-testid="org-estado" className={`font-medium ${o.status === "active" ? "" : "text-warn"}`}><span aria-hidden>{o.status === "active" ? "●" : "▲"} </span>{ORG_STATUS[o.status] ?? o.status}</dd></div>
              <div><dt className="text-xs text-muted">Saúde</dt><dd data-testid="org-saude">{healthText(o)}</dd></div>
              <div><dt className="text-xs text-muted">Último batimento</dt><dd>{o.last_heartbeat_at ? <time dateTime={o.last_heartbeat_at}>{when(o.last_heartbeat_at)}</time> : "—"}</dd></div>
              <div><dt className="text-xs text-muted">Criada · OLTs · ONUs</dt><dd><time dateTime={o.created_at}>{when(o.created_at)}</time> · {o.olts} · {o.onus}</dd></div>
            </dl>
          </section>
          <div className="grid gap-4 md:grid-cols-2">
            <section aria-label="Suspender ou reativar" className="panel p-4" data-testid="org-acao-estado">
              <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">{o.status === "active" ? "Suspender" : "Reativar"}</h2>
              <p className="mb-2 text-xs text-muted">{o.status === "active"
                ? "Enquanto suspensa, os usuários e o Edge desta organização recebem bloqueio. Nada é apagado; reativar devolve o acesso na hora."
                : "Reativar devolve o acesso aos usuários e ao Edge na hora, sem novo login."}</p>
              <form method="post" action={`/bff/plataforma/organizacoes/${id}/status`} className="grid gap-2">
                <input type="hidden" name="status" value={o.status === "active" ? "suspended" : "active"} />
                <label className="grid gap-1 text-sm">Motivo (3 a 200 caracteres)
                  <input name="reason" required minLength={3} maxLength={200} autoComplete="off" className={field} />
                </label>
                <div><button type="submit" data-testid="org-estado-enviar" className={o.status === "active" ? "min-h-touch rounded-btn border border-danger px-4 text-sm text-danger hover:bg-bg" : btn}>{o.status === "active" ? "Suspender organização" : "Reativar organização"}</button></div>
              </form>
            </section>
            <section aria-label="Renomear" className="panel p-4" data-testid="org-acao-nome">
              <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">Renomear</h2>
              <form method="post" action={`/bff/plataforma/organizacoes/${id}/rename`} className="grid gap-2">
                <label className="grid gap-1 text-sm">Novo nome (2 a 60 caracteres, sem repetir outro)
                  <input name="name" required minLength={2} maxLength={60} defaultValue={o.name} autoComplete="off" className={field} />
                </label>
                <div><button type="submit" data-testid="org-nome-enviar" className={btn}>Renomear</button></div>
              </form>
            </section>
          </div>
          <section aria-label="Recursos" className="panel overflow-x-auto" data-testid="org-recursos">
            <h2 className="p-3 pb-0 text-sm font-semibold uppercase tracking-wide text-muted">Recursos ({o.catalog.length})</h2>
            <table className="w-full min-w-[820px] text-sm">
              <caption className="sr-only">Recursos da organização: nome, padrão, valor atual, origem e a mudança com motivo</caption>
              <thead className="text-left text-muted"><tr>
                <th scope="col" className="p-3 font-medium">Recurso</th><th scope="col" className="p-3 font-medium">Padrão</th><th scope="col" className="p-3 font-medium">Atual</th>
                <th scope="col" className="p-3 font-medium">Origem</th><th scope="col" className="p-3 font-medium">Mudar</th>
              </tr></thead>
              <tbody className="divide-y divide-line">
                {o.catalog.map((f) => (
                  <tr key={f.feature} data-testid="org-recurso" data-feature={f.feature}>
                    <th scope="row" className="p-3 text-left font-mono text-xs font-medium">{f.feature}
                      {FEATURE_NOTES[f.feature] && <span className="block font-sans font-normal text-muted">{FEATURE_NOTES[f.feature]}</span>}
                    </th>
                    <td className="p-3">{f.default ? "ligado" : "desligado"}</td>
                    <td className={`p-3 font-medium ${f.enabled ? "text-ok" : ""}`} data-testid="org-recurso-atual">{f.enabled ? "Ligado" : "Desligado"}</td>
                    <td className="p-3 text-muted">{f.source === "tenant" ? "organização" : "padrão"}</td>
                    <td className="p-3">
                      <form method="post" action={`/bff/plataforma/organizacoes/${id}/features`} className="flex flex-wrap items-center gap-2">
                        <input type="hidden" name="feature" value={f.feature} />
                        <select name="state" aria-label={`Estado de ${f.feature}`} className="min-h-touch rounded-btn border border-line bg-bg px-2">
                          {featureChoices(f).map((s) => <option key={s} value={s}>{FEATURE_STATE_LABEL[s]}</option>)}
                        </select>
                        <input name="reason" required minLength={3} maxLength={200} autoComplete="off" placeholder="Motivo" aria-label={`Motivo da mudança de ${f.feature}`} className="min-h-touch w-40 rounded-btn border border-line bg-bg px-2" />
                        <button type="submit" className="min-h-touch rounded-btn border border-line px-3 text-sm hover:bg-bg">Aplicar</button>
                      </form>
                      {f.owner_only && <span className="mt-1 block text-xs text-muted" data-testid="org-recurso-dono">Só o dono liga, pela linha de comando.</span>}
                    </td>
                  </tr>))}
              </tbody>
            </table>
            {o.unknown_overrides.length > 0 && <p className="p-3 text-xs text-warn">Recursos na organização que esta versão não conhece: {o.unknown_overrides.join(", ")}.</p>}
          </section>
          <section aria-label="Histórico" className="panel p-4" data-testid="org-historico">
            <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">Histórico</h2>
            {o.history.length === 0 ? <p className="text-sm text-muted">Sem mudanças registradas.</p> : (
              <ul className="divide-y divide-line text-sm">
                {o.history.map((h, i) => (
                  <li key={`${h.at}-${i}`} data-testid="org-historico-linha" className="flex flex-wrap gap-x-3 py-1.5">
                    <time dateTime={h.at} className="tabular text-muted">{when(h.at)}</time>
                    <span className="font-medium">{ACTION_LABEL[h.action] ?? h.action}</span>
                    <span className="text-muted">{h.actor ?? "dono do sistema"}</span>
                    <span>{historyText(h)}</span>
                  </li>))}
              </ul>
            )}
          </section>
        </div>
      )}
    </AppShell>
  );
}

export const dynamic = "force-dynamic";
