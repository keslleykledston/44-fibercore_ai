import Link from "next/link";
import { notFound } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { DeviceThumb } from "@/components/DeviceThumb";
import { DataFreshness, ErrorState, PageHeader, StatusPill } from "@/components/ui";
import { apiSafe } from "@/lib/api";
import { featuresOn } from "@/lib/features";
import { CRED_HELP, FLEET_FLASH, UUID, type FleetOlt, type Pop } from "@/lib/fleet";

const field = "min-h-touch rounded-btn border border-line bg-bg px-3";

export default async function FrotaOlt({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ ok?: string | string[]; erro?: string | string[] }> }) {
  if (!(await featuresOn("fleet_manager"))) notFound();
  const { id } = await params;
  if (!UUID.test(id)) notFound();
  const sp = await searchParams;
  const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v) ?? "";
  const ok = one(sp.ok), erro = one(sp.erro);
  const [r, pops, assets] = await Promise.all([apiSafe<FleetOlt>(`/v1/fleet/olts/${id}`), apiSafe<{ items: Pop[] }>("/v1/pops"), featuresOn("device_assets")]);
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
      </div>
    </>,
  );
}
