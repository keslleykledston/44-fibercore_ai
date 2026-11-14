import Link from "next/link";
import { notFound } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { DeviceThumb } from "@/components/DeviceThumb";
import { EmptyState, ErrorState, PageHeader, StatusPill } from "@/components/ui";
import { apiSafe } from "@/lib/api";
import { featuresOn } from "@/lib/features";
import { OltReadiness } from "@/components/OltReadiness";
import { OltRegisterForm } from "@/components/OltRegisterForm";
import { FLEET_FLASH, oltLimitText, type FleetOlt, type Pop } from "@/lib/fleet";
import type { Edge } from "@/lib/types";

const field = "min-h-touch rounded-btn border border-line bg-bg px-3";

export default async function Frota({ searchParams }: { searchParams: Promise<{ ok?: string | string[]; erro?: string | string[]; atual?: string | string[]; max?: string | string[] }> }) {
  if (!(await featuresOn("fleet_manager"))) notFound();   // recurso desligado: a tela não existe
  const sp = await searchParams;
  const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v) ?? "";
  const ok = one(sp.ok), erro = one(sp.erro);
  const [olts, pops, edges, assets, secrets, provision] = await Promise.all([apiSafe<{ items: FleetOlt[] }>("/v1/fleet/olts"), apiSafe<{ items: Pop[] }>("/v1/pops"), apiSafe<Edge[]>("/v1/edges"), featuresOn("device_assets"), featuresOn("fleet_secrets"), featuresOn("fleet_provision")]);
  if (olts.status === 403) return <AppShell active="/rede" user="1"><ErrorState title="Sem permissão" hint="Seu papel não permite ver a frota de OLTs." /></AppShell>;
  const msg = erro === "limiteolts" ? oltLimitText(one(sp.atual), one(sp.max)) : ok && FLEET_FLASH[ok] ? FLEET_FLASH[ok] : erro && FLEET_FLASH[erro] ? FLEET_FLASH[erro] : null;
  const list = olts.data?.items ?? [], popList = pops.data?.items ?? [], edgeList = edges.data ?? [];
  return (
    <AppShell active="/rede" user="1">
      <PageHeader title="Frota de OLTs" subtitle="Cadastro, POP e identificação das OLTs. Somente leitura. Login, senha e community seguem cifrados até o Edge." helpSlug="rede/frota-de-olts">
        <Link href="/rede/homologacao" data-testid="frota-homologacao-link" className="inline-flex min-h-touch items-center rounded-btn border border-line px-3 text-sm hover:bg-bg">Homologação</Link>
        <Link href="/rede/conhecimento" data-testid="frota-conhecimento-link" className="inline-flex min-h-touch items-center rounded-btn border border-line px-3 text-sm hover:bg-bg">Base de conhecimento</Link>
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
                    <p className="font-medium"><Link href={`/rede/frota/${o.id}`} className="inline-block py-1 text-accent hover:underline">{o.name}</Link></p>
                    <p className="text-sm text-muted">{o.vendor} {o.model ?? "(modelo ainda não lido)"}{o.firmware ? ` · ${o.firmware}` : ""}</p>
                    <p className="mt-1 flex flex-wrap items-center gap-2 text-xs"><StatusPill value={o.support_level} /><span className="text-muted">{o.collected ? `${o.onu_count} ONUs` : "Ainda não coletada"}</span></p>
                    <p className="mt-1 text-xs text-muted">POP: {o.pop?.name ?? "—"} · Edge: {o.edge.name}{o.has_credential_ref ? " · credencial configurada" : " · sem credencial informada"}</p>
                    {o.connection.protocol && <div className="mt-1"><OltReadiness r={o.readiness} /></div>}
                  </div>
                </li>))}
            </ul>
          )}
        </section>
        <section aria-label="Cadastrar OLT" className="panel p-4" data-testid="frota-cadastro">
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">Cadastrar OLT</h2>
          <p className="mb-3 text-sm text-muted">Cria o registro na nuvem. A OLT também precisa estar na configuração do Edge, com o mesmo nome, ou ser entregue pelo assistente.</p>
          <OltRegisterForm edges={edgeList} pops={popList} secretsOn={secrets} provisionOn={provision} />
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
