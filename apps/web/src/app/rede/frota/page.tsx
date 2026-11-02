import Link from "next/link";
import { notFound } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { DeviceThumb } from "@/components/DeviceThumb";
import { EmptyState, ErrorState, PageHeader, StatusPill } from "@/components/ui";
import { apiSafe } from "@/lib/api";
import { featuresOn } from "@/lib/features";
import { CRED_HELP, FLEET_FLASH, FLEET_VENDORS, type FleetOlt, type Pop } from "@/lib/fleet";
import type { Edge } from "@/lib/types";

const field = "min-h-touch rounded-btn border border-line bg-bg px-3";

export default async function Frota({ searchParams }: { searchParams: Promise<{ ok?: string | string[]; erro?: string | string[] }> }) {
  if (!(await featuresOn("fleet_manager"))) notFound();   // recurso desligado: a tela não existe
  const sp = await searchParams;
  const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v) ?? "";
  const ok = one(sp.ok), erro = one(sp.erro);
  const [olts, pops, edges, assets] = await Promise.all([apiSafe<{ items: FleetOlt[] }>("/v1/fleet/olts"), apiSafe<{ items: Pop[] }>("/v1/pops"), apiSafe<Edge[]>("/v1/edges"), featuresOn("device_assets")]);
  if (olts.status === 403) return <AppShell active="/rede" user="1"><ErrorState title="Sem permissão" hint="Seu papel não permite ver a frota de OLTs." /></AppShell>;
  const msg = ok && FLEET_FLASH[ok] ? FLEET_FLASH[ok] : erro && FLEET_FLASH[erro] ? FLEET_FLASH[erro] : null;
  const list = olts.data?.items ?? [], popList = pops.data?.items ?? [], edgeList = edges.data ?? [];
  return (
    <AppShell active="/rede" user="1">
      <PageHeader title="Frota de OLTs" subtitle="Cadastro, POP e identificação das OLTs. Somente leitura: nada é enviado à OLT e a credencial fica no Edge." helpSlug="rede/frota-de-olts">
        <Link href="/rede" className="inline-flex min-h-touch items-center rounded-btn px-3 text-sm text-accent hover:underline">← Voltar para Rede</Link>
      </PageHeader>
      {msg && <p role={erro ? "alert" : "status"} data-testid="frota-flash" className={`mb-4 rounded-btn border px-3 py-2 text-sm ${erro ? "border-danger text-danger" : "border-ok text-ok"}`}>{msg}</p>}
      <div className="grid gap-6">
        <section aria-label="OLTs cadastradas" data-testid="frota-lista">
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">OLTs ({list.length})</h2>
          {olts.data === null ? <ErrorState title="Falha ao carregar as OLTs" /> : list.length === 0 ? <EmptyState title="Nenhuma OLT cadastrada" hint="Cadastre abaixo ou aguarde a primeira coleta do Edge." /> : (
            <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {list.map((o) => (
                <li key={o.id} data-testid="frota-olt" className="panel flex gap-3 p-3">
                  {assets && <DeviceThumb category="olt" vendor={o.vendor} model={o.model} width={72} decorative label />}
                  <div className="min-w-0">
                    <p className="font-medium"><Link href={`/rede/frota/${o.id}`} className="text-accent hover:underline">{o.name}</Link></p>
                    <p className="text-sm text-muted">{o.vendor} {o.model ?? "(modelo ainda não lido)"}{o.firmware ? ` · ${o.firmware}` : ""}</p>
                    <p className="mt-1 flex flex-wrap items-center gap-2 text-xs"><StatusPill value={o.support_level} /><span className="text-muted">{o.collected ? `${o.onu_count} ONUs` : "Ainda não coletada"}</span></p>
                    <p className="mt-1 text-xs text-muted">POP: {o.pop?.name ?? "—"} · Edge: {o.edge.name}{o.has_credential_ref ? " · credencial configurada" : " · sem credencial informada"}</p>
                  </div>
                </li>))}
            </ul>
          )}
        </section>
        <section aria-label="Cadastrar OLT" className="panel p-4" data-testid="frota-cadastro">
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">Cadastrar OLT</h2>
          <p className="mb-3 text-sm text-muted">O cadastro só cria o registro na nuvem. A OLT também precisa estar na configuração do Edge (feita por quem administra o Edge), com o mesmo nome. A primeira leitura preenche o modelo e o firmware.</p>
          <form method="post" action="/bff/frota/olts" className="grid gap-3 md:grid-cols-2">
            <label className="grid gap-1 text-sm">Nome da OLT<input name="name" required minLength={2} maxLength={60} className={field} placeholder="ex.: OLT-CENTRO-01" /></label>
            <label className="grid gap-1 text-sm">Fabricante<select name="vendor" required className={field}>{FLEET_VENDORS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
            <label className="grid gap-1 text-sm">Edge que vai coletar<select name="edge_id" required className={field}>{edgeList.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}</select></label>
            <label className="grid gap-1 text-sm">POP<select name="pop_id" className={field}><option value="">Sem POP</option>{popList.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
            <label className="grid gap-1 text-sm">Rótulo (opcional)<input name="label" maxLength={80} className={field} /></label>
            <label className="grid gap-1 text-sm">Nome da credencial no Edge (opcional)<input name="credential_ref" maxLength={64} autoComplete="off" spellCheck={false} className={`${field} font-mono`} placeholder="ex.: olt-centro-01" />
              <span className="text-xs text-muted">{CRED_HELP}</span></label>
            <div className="md:col-span-2"><button type="submit" data-testid="frota-cadastrar" className="min-h-touch rounded-btn border border-line px-4 text-sm hover:bg-bg" disabled={edgeList.length === 0}>Cadastrar OLT</button>
              {edgeList.length === 0 && <span className="ml-3 text-xs text-muted">Nenhum Edge disponível.</span>}</div>
          </form>
        </section>
        <section aria-label="POPs" className="panel p-4" data-testid="frota-pops">
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">POPs ({popList.length})</h2>
          {popList.length > 0 && <ul className="mb-3 divide-y divide-line text-sm">{popList.map((p) => <li key={p.id} data-testid="frota-pop" className="py-1.5"><span className="font-medium">{p.name}</span>{p.code ? <span className="text-muted"> · {p.code}</span> : null}<span className="text-muted"> · {p.olts ?? 0} OLT(s)</span>{p.note ? <span className="block text-xs text-muted">{p.note}</span> : null}</li>)}</ul>}
          <form method="post" action="/bff/frota/pops" className="flex flex-wrap items-end gap-3">
            <label className="grid gap-1 text-sm">Nome do POP<input name="name" required minLength={2} maxLength={60} className={field} /></label>
            <label className="grid gap-1 text-sm">Código (opcional)<input name="code" maxLength={24} className={field} /></label>
            <label className="grid gap-1 text-sm">Observação (opcional)<input name="note" maxLength={200} className={field} /></label>
            <button type="submit" data-testid="frota-criar-pop" className="min-h-touch rounded-btn border border-line px-4 text-sm hover:bg-bg">Criar POP</button>
          </form>
        </section>
      </div>
    </AppShell>
  );
}
