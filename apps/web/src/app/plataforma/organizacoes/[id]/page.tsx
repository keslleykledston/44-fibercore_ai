import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { AdminTabs } from "@/components/AdminTabs";
import { AppShell } from "@/components/AppShell";
import { ErrorState, PageHeader } from "@/components/ui";
import { apiSafe } from "@/lib/api";
import { ACTION_LABEL, CLOSURE_STATE, FEATURE_NOTES, FEATURE_STATE_LABEL, LIMIT_FIELDS, ORG_ERRORS, ORG_FLASH, ORG_STATUS, type PlatformOrgDetail, UUID_FORMAT, closureCommands, featureChoices, graceOver, healthText, historyText } from "@/lib/platform";
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
          {o.limits && (
            <section aria-label="Limites técnicos" className="panel overflow-x-auto" data-testid="org-limites">
              <h2 className="p-3 pb-0 text-sm font-semibold uppercase tracking-wide text-muted">Limites técnicos</h2>
              <p className="px-3 pt-1 text-xs text-muted">Protegem o servidor e dividem a carga entre organizações. Só o operador altera; a organização não vê nem muda estes valores. Reduzir abaixo do uso atual só impede novos cadastros; nada existente é removido.</p>
              <form method="post" action={`/bff/plataforma/organizacoes/${id}/limits`}>
                <table className="w-full min-w-[820px] text-sm">
                  <caption className="sr-only">Limites técnicos da organização: uso atual, limite em vigor, origem e novo valor</caption>
                  <thead className="text-left text-muted"><tr>
                    <th scope="col" className="p-3 font-medium">Limite</th><th scope="col" className="p-3 font-medium">Uso</th><th scope="col" className="p-3 font-medium">Em vigor</th>
                    <th scope="col" className="p-3 font-medium">Origem</th><th scope="col" className="p-3 font-medium">Novo valor</th><th scope="col" className="p-3 font-medium">Padrão</th>
                  </tr></thead>
                  <tbody className="divide-y divide-line">
                    {LIMIT_FIELDS.map((f) => {
                      const used = f.key === "max_edges" ? o.limits!.usage.edges : f.key === "max_olts" ? o.limits!.usage.olts : f.key === "max_members" ? o.limits!.usage.members : null;
                      const adjusted = o.limits!.values[f.key] !== null;
                      return (
                        <tr key={f.key} data-testid="org-limite" data-limit={f.key}>
                          <th scope="row" className="p-3 text-left font-medium">{f.label}{f.unit && <span className="block text-xs font-normal text-muted">{f.unit}</span>}</th>
                          <td className="p-3 tabular" data-testid="org-limite-uso">{used === null ? "—" : used}
                            {f.key === "max_members" && <span className="block text-xs font-normal text-muted" data-testid="org-limite-convites">+ {o.limits!.usage.invites_open ?? 0} convite{(o.limits!.usage.invites_open ?? 0) === 1 ? "" : "s"} aberto{(o.limits!.usage.invites_open ?? 0) === 1 ? "" : "s"} (lugar reservado)</span>}
                          </td>
                          <td className="p-3 tabular font-medium" data-testid="org-limite-vigor">{o.limits!.effective[f.key]}</td>
                          <td className="p-3"><span data-testid="org-limite-origem" className={`rounded-btn border px-2 py-0.5 text-xs ${adjusted ? "border-accent text-accent" : "border-line text-muted"}`}>{adjusted ? "ajustado" : "padrão"}</span></td>
                          <td className="p-3"><input type="number" name={f.key} min={f.min} max={f.max} step={1} inputMode="numeric" autoComplete="off" placeholder={String(o.limits!.effective[f.key])} aria-label={`Novo valor de ${f.label} (${f.min} a ${f.max}; vazio não muda)`} className="min-h-touch w-32 rounded-btn border border-line bg-bg px-2" /></td>
                          <td className="p-3">
                            <label className="inline-flex min-h-touch items-center gap-2 text-xs"><input type="checkbox" name={`default_${f.key}`} value="1" className="size-4" />Voltar ao padrão ({o.limits!.defaults[f.key]})</label>
                          </td>
                        </tr>);
                    })}
                  </tbody>
                </table>
                <div className="flex flex-wrap items-end gap-2 p-3 pt-0">
                  <label className="grid gap-1 text-sm">Motivo (3 a 200 caracteres)
                    <input name="reason" required minLength={3} maxLength={200} autoComplete="off" className={`${field} w-72`} />
                  </label>
                  <button type="submit" data-testid="org-limites-enviar" className={btn}>Aplicar limites</button>
                </div>
              </form>
            </section>
          )}
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
          {(o.status === "suspended" || o.closure?.state === "requested") && (
            <section aria-label="Encerrar organização" className="panel p-4" data-testid="org-encerramento">
              <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">Encerrar organização</h2>
              <p className="mb-2 text-xs text-muted">Esta tela <strong>não apaga nada</strong> e o operador <strong>não baixa dados</strong> da organização. Pedir o encerramento só abre uma carência de 7 dias; depois dela, quem exporta e apaga é o dono do sistema, no servidor. Reativar a organização cancela o pedido. Organização de demonstração nunca é encerrada.</p>
              {o.closure?.state === "requested" ? (
                <div className="grid gap-3 text-sm">
                  <dl className="grid gap-x-4 gap-y-2 sm:grid-cols-3">
                    <div><dt className="text-xs text-muted">Estado</dt><dd data-testid="org-encerramento-estado" className="font-medium text-warn"><span aria-hidden>▲ </span>{CLOSURE_STATE[o.closure.state]}</dd></div>
                    <div><dt className="text-xs text-muted">Pedido em</dt><dd><time dateTime={o.closure.requested_at}>{when(o.closure.requested_at)}</time></dd></div>
                    <div><dt className="text-xs text-muted">Carência até</dt><dd data-testid="org-encerramento-carencia"><time dateTime={o.closure.earliest_close_at}>{when(o.closure.earliest_close_at)}</time>{graceOver(o.closure) ? " (vencida)" : ""}</dd></div>
                  </dl>
                  <p className="text-muted" data-testid="org-encerramento-motivo">Motivo: {o.closure.reason}</p>
                  {o.closure.export_at && <p className="text-xs text-muted" data-testid="org-encerramento-export">Exportação registrada em <time dateTime={o.closure.export_at}>{when(o.closure.export_at)}</time> (sha256 {o.closure.export_sha256?.slice(0, 12)}…).</p>}
                  {graceOver(o.closure) ? (() => {
                    const c = closureCommands(o.tenant_id, o.name);
                    return (
                      <div className="grid gap-2" data-testid="org-encerramento-dono">
                        <p>Carência vencida. Passo a passo <strong>para o dono</strong>, no servidor (a tela não executa nada):</p>
                        <ol className="ml-5 list-decimal space-y-1">
                          <li>Exporte os dados (guarde o arquivo com cuidado: ele contém dado pessoal de cliente final):<pre className="mt-1 overflow-x-auto rounded-btn border border-line bg-bg p-2 text-xs" data-testid="org-cmd-exportar">{c.exportar}</pre></li>
                          <li>Confira com <code>--dry-run</code> e apague (irreversível):<pre className="mt-1 overflow-x-auto rounded-btn border border-line bg-bg p-2 text-xs" data-testid="org-cmd-encerrar">{c.encerrar}</pre></li>
                        </ol>
                        <p className="text-xs text-muted">Os dois comandos rodam pelo serviço <code>migrate</code> (<code>python -m app.cli …</code>). O nome precisa ser exatamente o da organização.</p>
                      </div>);
                  })() : <p className="text-muted" data-testid="org-encerramento-aguarde">Dentro da carência: nada a fazer pelo dono ainda. Você pode cancelar o pedido a qualquer momento.</p>}
                  <form method="post" action={`/bff/plataforma/organizacoes/${id}/closure/cancel`} className="grid gap-2">
                    <label className="grid gap-1 text-sm">Motivo do cancelamento (3 a 200 caracteres)
                      <input name="reason" required minLength={3} maxLength={200} autoComplete="off" className={field} />
                    </label>
                    <div><button type="submit" data-testid="org-encerramento-cancelar" className={btn}>Cancelar pedido</button></div>
                  </form>
                </div>
              ) : (
                <form method="post" action={`/bff/plataforma/organizacoes/${id}/closure`} className="grid gap-2">
                  {o.closure?.state === "cancelled" && <p className="text-xs text-muted" data-testid="org-encerramento-anterior">Pedido anterior cancelado{o.closure.cancelled_at ? ` em ${when(o.closure.cancelled_at)}` : ""}.</p>}
                  <label className="grid gap-1 text-sm">Motivo do pedido (3 a 200 caracteres)
                    <input name="reason" required minLength={3} maxLength={200} autoComplete="off" className={field} />
                  </label>
                  <div><button type="submit" data-testid="org-encerramento-pedir" className="min-h-touch rounded-btn border border-danger px-4 text-sm text-danger hover:bg-bg">Pedir encerramento</button></div>
                </form>
              )}
            </section>
          )}
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
