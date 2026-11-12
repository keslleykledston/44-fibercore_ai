import Link from "next/link";
import { notFound } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { EmptyState, ErrorState, PageHeader } from "@/components/ui";
import { apiSafe } from "@/lib/api";
import { featuresOn } from "@/lib/features";
import { ACS_FLASH, countText, errorText, HEALTH_TEXT, kindLabel, KIND_LABEL, seenText, type AcsList } from "@/lib/acs";
import type { Edge, MeInfo } from "@/lib/types";

const field = "min-h-touch rounded-btn border border-line bg-bg px-3";
const btn = "min-h-touch rounded-btn border border-line px-4 text-sm hover:bg-bg";

/** ACS por organização (ADR-0046 D2): o CADASTRO fica na nuvem; a URL e a senha do GenieACS ficam no Edge. Sem JavaScript: formulários que passam pelo BFF. */
export default async function Acs({ searchParams }: { searchParams: Promise<{ ok?: string | string[]; erro?: string | string[] }> }) {
  if (!(await featuresOn("acs_registry"))) notFound();   // recurso desligado: a tela não existe
  const sp = await searchParams;
  const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v) ?? "";
  const ok = one(sp.ok), erro = one(sp.erro);
  const [acs, edges, me] = await Promise.all([apiSafe<AcsList>("/v1/acs"), apiSafe<Edge[]>("/v1/edges"), apiSafe<MeInfo>("/v1/auth/me")]);
  if (acs.status === 403) return <AppShell active="/rede" user="1"><ErrorState title="Sem permissão" hint="Seu papel não permite ver os ACS cadastrados." /></AppShell>;
  const msg = ok && ACS_FLASH[ok] ? ACS_FLASH[ok] : erro && ACS_FLASH[erro] ? ACS_FLASH[erro] : null;
  const list = acs.data?.items ?? [], kinds = (acs.data?.kinds ?? []).filter((k) => k in KIND_LABEL), edgeList = edges.data ?? [];
  const canManage = !!me.data?.permissions.some((p) => p.name === "acs:manage");
  const now = Date.now();
  return (
    <AppShell active="/rede" user="1">
      <PageHeader title="ACS" subtitle="O cadastro do ACS de cada Edge e se ele está respondendo. A URL e a senha do GenieACS ficam no Edge, nunca aqui." helpSlug="rede/acs">
        <Link href="/rede/frota" className="inline-flex min-h-touch items-center rounded-btn border border-line px-3 text-sm hover:bg-bg">Frota de OLTs</Link>
        <Link href="/rede" className="inline-flex min-h-touch items-center rounded-btn px-3 text-sm text-accent hover:underline">← Voltar para Rede</Link>
      </PageHeader>
      {msg && <p role={erro ? "alert" : "status"} data-testid="acs-flash" className={`mb-4 rounded-btn border px-3 py-2 text-sm ${erro ? "border-danger text-danger" : "border-ok text-ok"}`}>{msg}</p>}
      <div className="grid gap-6">
        <section aria-label="ACS cadastrados" data-testid="acs-lista">
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">ACS cadastrados ({list.length})</h2>
          {acs.data === null ? <ErrorState title="Falha ao carregar os ACS" /> : list.length === 0 ? <EmptyState title="Nenhum ACS cadastrado" hint={canManage ? "Cadastre abaixo o ACS de um Edge." : "Quem administra o provedor cadastra o ACS de cada Edge."} /> : (
            <ul className="grid gap-3 md:grid-cols-2">
              {list.map((a) => {
                const h = HEALTH_TEXT[a.health];
                const err = errorText(a.last_error_code);
                return (
                  <li key={a.id} data-testid="acs-item" data-health={a.health} data-enabled={a.enabled ? "1" : "0"} className="panel grid gap-2 p-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="font-medium">{a.name}</h3>
                      <span className="rounded-full bg-accent-soft px-2.5 py-0.5 text-xs font-medium text-text">{kindLabel(a.kind)}</span>
                      <span data-testid="acs-ativo" className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium ${a.enabled ? "bg-ok-soft text-ok" : "bg-stale-soft text-muted"}`}><span aria-hidden>{a.enabled ? "●" : "○"}</span>{a.enabled ? "Ativo" : "Inativo"}</span>
                      <span data-testid="acs-saude" className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium ${h.cls}`}><span aria-hidden>{h.symbol}</span>{h.label}</span>
                    </div>
                    {a.label && <p className="text-sm text-muted">{a.label}</p>}
                    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
                      <dt className="text-muted">Edge</dt><dd>{a.edge.name}</dd>
                      <dt className="text-muted">Dispositivos</dt><dd data-testid="acs-dispositivos">{countText(a.device_count)}</dd>
                      <dt className="text-muted">Última leitura</dt><dd data-testid="acs-visto">{seenText(a.last_seen_at, now)}</dd>
                      <dt className="text-muted">Último erro</dt><dd data-testid="acs-erro">{err ?? "nenhum"}</dd>
                      <dt className="text-muted">Identificador</dt><dd><code data-testid="acs-id" className="break-all text-xs">{a.id}</code></dd>
                    </dl>
                    {canManage && (
                      <div className="flex flex-wrap items-start gap-3">
                        <form method="post" action={`/bff/acs/${a.id}`}>
                          <input type="hidden" name="acao" value={a.enabled ? "desativar" : "ativar"} />
                          <button type="submit" data-testid="acs-alternar" className={btn}>{a.enabled ? "Desativar" : "Ativar"}<span className="sr-only"> {a.name}</span></button>
                        </form>
                        <details className="min-w-0 flex-1">
                          <summary className="inline-flex min-h-touch cursor-pointer items-center rounded-btn border border-line px-4 text-sm hover:bg-bg">Renomear<span className="sr-only"> {a.name}</span></summary>
                          <form method="post" action={`/bff/acs/${a.id}`} className="mt-2 flex flex-wrap items-end gap-3">
                            <input type="hidden" name="acao" value="salvar" />
                            <label className="grid gap-1 text-sm">Nome<input name="name" required minLength={2} maxLength={60} defaultValue={a.name} className={field} /></label>
                            <label className="grid gap-1 text-sm">Rótulo (opcional)<input name="label" maxLength={80} defaultValue={a.label ?? ""} className={field} /></label>
                            <button type="submit" data-testid="acs-salvar" className={btn}>Salvar</button>
                          </form>
                        </details>
                      </div>
                    )}
                  </li>);
              })}
            </ul>
          )}
          {acs.data?.truncated && <p className="mt-2 text-xs text-muted">A lista foi cortada no limite da tela.</p>}
        </section>
        {canManage ? (
          <section aria-label="Cadastrar ACS" className="panel p-4" data-testid="acs-cadastro">
            <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">Cadastrar ACS</h2>
            <p className="mb-3 text-sm text-muted">Cada Edge tem no máximo <strong>um ACS ativo</strong>. O cadastro guarda só o nome, o tipo e o Edge: <strong>a URL e a senha do GenieACS ficam no Edge</strong> (arquivo <code>config.json</code>) e nunca são pedidas aqui. Depois de cadastrar, copie o identificador para o campo <code>nbi_cloud_id</code> do Edge e reinicie o serviço dele.</p>
            {edgeList.length === 0 || kinds.length === 0 ? <EmptyState title="Sem Edge para escolher" hint="Nenhum Edge deste provedor foi encontrado." /> : (
              <form method="post" action="/bff/acs" className="flex flex-wrap items-end gap-3">
                <label className="grid gap-1 text-sm">Nome do ACS<input name="name" required minLength={2} maxLength={60} className={field} /></label>
                <label className="grid gap-1 text-sm">Tipo<select name="kind" required className={field} defaultValue={kinds[0]}>{kinds.map((k) => <option key={k} value={k}>{kindLabel(k)}</option>)}</select></label>
                <label className="grid gap-1 text-sm">Edge<select name="edge_id" required className={field}>{edgeList.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}</select></label>
                <label className="grid gap-1 text-sm">Rótulo (opcional)<input name="label" maxLength={80} className={field} /></label>
                <label className="inline-flex min-h-touch items-center gap-2 text-sm"><input type="checkbox" name="enabled" value="1" defaultChecked className="h-5 w-5" />Ativar agora</label>
                <button type="submit" data-testid="acs-cadastrar" className={btn}>Cadastrar ACS</button>
              </form>
            )}
          </section>
        ) : (
          <p className="text-sm text-muted" data-testid="acs-somente-leitura">Seu papel só permite ver os ACS. Quem administra o provedor cadastra e ativa.</p>
        )}
      </div>
    </AppShell>
  );
}
