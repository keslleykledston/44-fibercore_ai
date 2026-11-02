import Link from "next/link";
import { notFound } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { DeviceThumb } from "@/components/DeviceThumb";
import { EmptyState, PageHeader } from "@/components/ui";
import { ASSETS, FIDELITY_LABEL, FIDELITY_NOTE, VENDOR_LABEL, searchAssets, vendorsOf, type DeviceCategory } from "@/lib/deviceAssets";
import { featuresOn } from "@/lib/features";

const STATUS_NOTE: Record<string, string> = {
  ART_READY_DRIVER_NOT_HOMOLOGATED: "Arte pronta · driver NÃO homologado",
  ART_READY_NOT_LIVE_INTEGRATED: "Arte pronta · sem integração ao vivo",
};
const field = "min-h-touch rounded-btn border border-line bg-bg px-3";

export default async function Catalogo({ searchParams }: { searchParams: Promise<{ q?: string | string[]; tipo?: string | string[]; fab?: string | string[] }> }) {
  if (!(await featuresOn("device_assets"))) notFound();   // recurso desligado: a tela não existe
  const raw = await searchParams;
  const one = (v: string | string[] | undefined): string => (Array.isArray(v) ? v[0] ?? "" : v ?? "");   // um parâmetro repetido (?q=a&q=b) chega como lista: vale o primeiro valor, sempre texto
  const sp = { q: one(raw.q), tipo: one(raw.tipo), fab: one(raw.fab) };
  const q = sp.q.slice(0, 60);
  const tipo: DeviceCategory | null = sp.tipo === "olt" || sp.tipo === "onu_ont" ? sp.tipo : null;
  const vendors = vendorsOf();
  const fab = vendors.some((v) => v.vendor === sp.fab) ? sp.fab : null;   // só fabricante que existe no catálogo
  const items = searchAssets(q, { category: tipo, vendor: fab });
  return (
    <AppShell active="/rede" user="1">
      <PageHeader title="Catálogo de equipamentos" subtitle="Ilustrações esquemáticas por fabricante e modelo. Somente arte: nada aqui indica suporte, portas ou estado." helpSlug="rede/catalogo-de-equipamentos">
        <Link href="/rede" className="inline-flex min-h-touch items-center rounded-btn px-3 text-sm text-accent hover:underline">← Voltar para Rede</Link>
      </PageHeader>
      <p data-testid="catalogo-aviso" className="mb-4 rounded-btn border border-line px-3 py-2 text-sm text-muted">{FIDELITY_NOTE} Ter uma imagem aqui <strong>não</strong> quer dizer que o FiberCore lê ou configura o equipamento.</p>
      <form method="get" className="mb-4 flex flex-wrap items-end gap-3" data-testid="catalogo-filtros">
        <label className="grid gap-1 text-sm">Buscar por fabricante ou modelo<input name="q" defaultValue={q} maxLength={60} placeholder="ex.: huawei ma5608" className={field} /></label>
        <label className="grid gap-1 text-sm">Tipo<select name="tipo" defaultValue={tipo ?? ""} className={field}><option value="">Todos</option><option value="olt">OLT</option><option value="onu_ont">ONU/ONT</option></select></label>
        <label className="grid gap-1 text-sm">Fabricante<select name="fab" defaultValue={fab ?? ""} className={field}><option value="">Todos</option>{vendors.map((v) => <option key={v.vendor} value={v.vendor}>{VENDOR_LABEL[v.vendor] ?? v.vendor}</option>)}</select></label>
        <button type="submit" className="min-h-touch rounded-btn border border-line px-4 text-sm hover:bg-bg">Filtrar</button>
      </form>
      <p data-testid="catalogo-contagem" className="mb-3 text-sm text-muted">{items.length} de {ASSETS.length} equipamentos · {vendors.length} fabricantes</p>
      {items.length === 0 ? <EmptyState title="Nenhum equipamento encontrado" hint="Um modelo fora do catálogo aparece com o desenho neutro da família, sem portas inventadas." /> : (
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4" data-testid="catalogo-grade">
          {items.map((a) => (
            <li key={a.asset_id} data-testid="catalogo-item" data-asset={a.asset_id} className="panel flex flex-col gap-2 p-3">
              <DeviceThumb category={a.device_type} vendor={a.vendor} model={a.model} width={180} />
              <div>
                <p className="font-medium">{VENDOR_LABEL[a.vendor] ?? a.vendor} {a.model}</p>
                <p className="text-xs text-muted">{a.device_type === "olt" ? "OLT" : "ONU/ONT"}{a.technology ? ` · ${a.technology}` : ""}{a.port_count_nominal ? ` · ${a.port_count_nominal} portas nominais (as reais vêm do inventário)` : ""}</p>
              </div>
              <p className="mt-auto flex flex-wrap gap-1 text-xs">
                <span className="rounded-btn border border-line px-2 py-0.5" data-testid="catalogo-fidelidade">{FIDELITY_LABEL.SCHEMATIC}</span>
                <span className="rounded-btn border border-line px-2 py-0.5 text-muted">{STATUS_NOTE[a.status] ?? "Arte pronta"}</span>
              </p>
            </li>
          ))}
        </ul>
      )}
    </AppShell>
  );
}
