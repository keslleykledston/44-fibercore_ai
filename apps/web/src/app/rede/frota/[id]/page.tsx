import Link from "next/link";
import { notFound } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { DeviceThumb } from "@/components/DeviceThumb";
import { DataFreshness, ErrorState, PageHeader, StatusPill } from "@/components/ui";
import { apiSafe } from "@/lib/api";
import { featuresOn } from "@/lib/features";
import { CRED_HELP, FLEET_FLASH, JOB_LABEL, UUID, uptimeText, type ConnectionTests, type FleetOlt, type Pop } from "@/lib/fleet";

const field = "min-h-touch rounded-btn border border-line bg-bg px-3";

export default async function FrotaOlt({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ ok?: string | string[]; erro?: string | string[] }> }) {
  if (!(await featuresOn("fleet_manager"))) notFound();
  const { id } = await params;
  if (!UUID.test(id)) notFound();
  const sp = await searchParams;
  const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v) ?? "";
  const ok = one(sp.ok), erro = one(sp.erro);
  const [r, pops, assets, tests] = await Promise.all([apiSafe<FleetOlt>(`/v1/fleet/olts/${id}`), apiSafe<{ items: Pop[] }>("/v1/pops"), featuresOn("device_assets"), apiSafe<ConnectionTests>(`/v1/fleet/olts/${id}/connection-tests`)]);
  if (r.status === 404) notFound();
  const shell = (c: React.ReactNode) => <AppShell active="/rede" user="1">{c}</AppShell>;
  if (r.status === 403) return shell(<ErrorState title="Sem permissão" hint="Seu papel não permite ver esta OLT." />);
  if (!r.data) return shell(<ErrorState title="Não foi possível carregar a OLT" hint="Recarregue a página." />);
  const o = r.data;
  const msg = ok && FLEET_FLASH[ok] ? FLEET_FLASH[ok] : erro && FLEET_FLASH[erro] ? FLEET_FLASH[erro] : null;
  return shell(
    <>
      <PageHeader title={o.name} subtitle="Cadastro e identificação da OLT. Somente leitura: nada é enviado à OLT." helpSlug="rede/frota-de-olts">
        <Link href="/rede/frota" className="inline-flex min-h-touch items-center rounded-btn px-3 text-sm text-accent hover:underline">← Voltar para a Frota</Link>
      </PageHeader>
      {msg && <p role={erro ? "alert" : "status"} data-testid="frota-flash" className={`mb-4 rounded-btn border px-3 py-2 text-sm ${erro ? "border-danger text-danger" : "border-ok text-ok"}`}>{msg}</p>}
      <div className="grid gap-4 md:grid-cols-2" data-testid="frota-detalhe">
        <section className="panel flex gap-4 p-4" aria-label="Identificação">
          {assets && <DeviceThumb category="olt" vendor={o.vendor} model={o.model} width={120} label />}
          <dl className="grid gap-1 text-sm">
            <div><dt className="text-xs text-muted">Fabricante · modelo</dt><dd>{o.vendor} {o.model ?? "— (ainda não lido pelo Edge)"}</dd></div>
            <div><dt className="text-xs text-muted">Firmware</dt><dd>{o.firmware ?? "—"}</dd></div>
            <div><dt className="text-xs text-muted">Nível do driver</dt><dd><StatusPill value={o.support_level} /></dd></div>
            <div><dt className="text-xs text-muted">Última coleta</dt><dd>{o.observed_at ? <DataFreshness freshness="fresh" observedAt={o.observed_at} /> : "Ainda não coletada"}</dd></div>
            <div><dt className="text-xs text-muted">Edge</dt><dd>{o.edge.name}</dd></div>
            <div><dt className="text-xs text-muted">Credencial</dt><dd data-testid="frota-credencial">{o.has_credential_ref ? "Informada (o nome não é mostrado)" : "Não informada"}</dd></div>
            {o.collected && <div><Link href={`/rede?olt=${o.id}`} className="text-accent underline underline-offset-2">Ver as ONUs desta OLT</Link></div>}
          </dl>
        </section>
        <section className="panel p-4" aria-label="Cadastro">
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">Cadastro</h2>
          <form method="post" action={`/bff/frota/olts/${o.id}`} className="grid gap-3">
            <label className="grid gap-1 text-sm">POP<select name="pop_id" defaultValue={o.pop?.id ?? ""} className={field}><option value="">Sem POP</option>{(pops.data?.items ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
            <label className="grid gap-1 text-sm">Rótulo<input name="label" defaultValue={o.label ?? ""} maxLength={80} className={field} /></label>
            <label className="grid gap-1 text-sm">{o.has_credential_ref ? "Substituir o nome da credencial no Edge" : "Nome da credencial no Edge"}<input name="credential_ref" defaultValue="" maxLength={64} autoComplete="off" spellCheck={false} placeholder={o.has_credential_ref ? "deixe vazio para manter a atual" : "ex.: olt-centro-01"} className={`${field} font-mono`} />
              <span className="text-xs text-muted">{CRED_HELP} O nome já informado não é mostrado de volta.</span></label>
            {o.has_credential_ref && <label className="flex items-center gap-2 text-sm"><input type="checkbox" name="remover_credencial" value="1" /> Remover o nome da credencial</label>}
            <div><button type="submit" data-testid="frota-salvar" className="min-h-touch rounded-btn border border-line px-4 text-sm hover:bg-bg">Salvar</button></div>
          </form>
        </section>
        <section className="panel p-4 md:col-span-2" aria-label="Teste de conexão" data-testid="frota-teste">
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">Teste de conexão</h2>
          <p className="mb-3 text-sm text-muted">O Edge lê a identidade da OLT (modelo e firmware) na próxima janela de coleta, <strong>somente leitura</strong>: nada é configurado. Limite: 1 teste a cada 15 minutos e 4 por hora por OLT. Um resultado recente já guardado responde sem consultar a OLT.</p>
          {tests.data === null ? <p className="text-sm text-muted">O histórico de testes não está disponível agora.</p> : (
            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <form method="post" action={`/bff/frota/olts/${o.id}/testar`} className="mb-3 flex flex-wrap items-center gap-3">
                  <button type="submit" data-testid="frota-testar" disabled={tests.data.budget.wait_seconds > 0} className="min-h-touch rounded-btn border border-line px-4 text-sm hover:bg-bg disabled:opacity-60">Testar conexão</button>
                  <span data-testid="frota-orcamento" className="text-xs text-muted">{tests.data.budget.wait_seconds > 0 ? `Próximo teste em cerca de ${Math.ceil(tests.data.budget.wait_seconds / 60)} min. ` : ""}{tests.data.budget.used_last_hour} de {tests.data.budget.max_per_hour} na última hora.</span>
                </form>
                {tests.data.latest ? (
                  <dl className="grid gap-1 text-sm" data-testid="frota-identidade">
                    <div><dt className="text-xs text-muted">Lido pelo Edge há {Math.floor(tests.data.latest.age_seconds / 60)} min{tests.data.latest.stale ? " (leitura antiga)" : ""}</dt><dd className="font-medium">{tests.data.latest.identity.model} · {tests.data.latest.identity.firmware}</dd></div>
                    <div><dt className="text-xs text-muted">Patch · tempo ligada</dt><dd>{tests.data.latest.identity.patch} · {uptimeText(tests.data.latest.identity.uptime_seconds)}</dd></div>
                    <div><dt className="text-xs text-muted">Fabricante (o do cadastro; a leitura não o informa)</dt><dd>{tests.data.latest.identity.vendor}</dd></div>
                    <div data-testid="frota-confere" className={tests.data.latest.identity.matches_collected === false ? "text-danger" : "text-muted"}>
                      {tests.data.latest.identity.matches_collected === true ? "Confere com a identidade que a coleta já tinha." : tests.data.latest.identity.matches_collected === false ? "DIVERGE da identidade que a coleta já tinha: confira o cadastro e a configuração do Edge." : "Ainda não há coleta para comparar."}
                    </div>
                  </dl>
                ) : <p className="text-sm text-muted" data-testid="frota-sem-identidade">Nenhum teste concluído ainda.</p>}
              </div>
              <div>
                <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">Pedidos recentes</h3>
                {tests.data.items.length === 0 ? <p className="text-sm text-muted">Nenhum teste pedido.</p> : (
                  <ul className="divide-y divide-line text-sm" data-testid="frota-testes">{tests.data.items.map((t) => (
                    <li key={t.id} className="py-1.5"><span data-testid="volatile">{new Date(t.requested_at).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" })}</span> · {t.outcome === "cached" ? "Respondido do que já estava guardado" : `Pedido ao Edge: ${t.job_status ? JOB_LABEL[t.job_status] ?? t.job_status : "—"}`}</li>))}</ul>
                )}
                <p className="mt-2 text-xs"><Link href={`/rede/frota/${o.id}`} className="text-accent underline underline-offset-2">Atualizar</Link></p>
              </div>
            </div>
          )}
        </section>
      </div>
    </>,
  );
}
