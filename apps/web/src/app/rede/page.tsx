import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { DataFreshness, EmptyState, ErrorState, PageHeader, StatusPill } from "@/components/ui";
import { DevicesTabs } from "@/components/DevicesTabs";
import { OltQueries } from "@/components/OltQueries";
import { OnuTable } from "@/components/OnuTable";
import { OnuWorkspace } from "@/components/OnuWorkspace";
import { PonMatrix } from "@/components/PonMatrix";
import { PonTree } from "@/components/PonTree";
import { apiSafe } from "@/lib/api";
import { featuresOn } from "@/lib/features";
import { summarizePons } from "@/lib/faceplates";
import type { Olt, Onu } from "@/lib/types";

const READ_LIMIT = 1000;   // teto da API por consulta; acima disso a tela avisa que a lista é parcial (nunca finge ser completa)
const PON_RE = /^[0-9]{1,3}(\/[0-9]{1,3}){1,3}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default async function Rede({ searchParams }: { searchParams: Promise<{ serial?: string; olt?: string; pon?: string }> }) {
  const { serial, olt: oltParam, pon: ponParam } = await searchParams;
  const quick = await featuresOn("onu_quick_inspector");
  const serialQ = serial && /^[A-Za-z0-9._-]{1,64}$/.test(serial) ? `&serial=${encodeURIComponent(serial.toUpperCase())}` : "";
  const ontConfig = quick ? await featuresOn("ont_config") : false;
  const speed = quick ? await featuresOn("speed_diagnostics") : false;   // ADR-0038: desligada, a aba "Teste de banda" não existe

  if (!quick) {   // caminho legado (flag desligada): exatamente como era
    const [olts, onus] = await Promise.all([apiSafe<Olt[]>("/v1/olts?limit=200"), apiSafe<Onu[]>(`/v1/onus?limit=200${serialQ}`)]);
    if (olts.status === 403 || onus.status === 403) return <AppShell active="/rede" user="1"><ErrorState title="Sem permissão" hint="Seu papel não permite ver o inventário." /></AppShell>;
    return (
      <AppShell active="/rede" user="1">
        <PageHeader title="Rede" subtitle="OLTs e ONUs com frescor e fonte do dado" helpSlug="rede/consultar-onu" />
        <DevicesTabs current="/rede" />
        <div data-testid="onu-inventory-ready" className="grid gap-6 lg:grid-cols-[320px_1fr]">
          <section aria-label="OLTs">
            <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">OLTs</h2>
            {olts.data === null ? <ErrorState title="Falha ao carregar OLTs" /> : olts.data.length === 0 ? <EmptyState title="Nenhuma OLT coletada" hint="Aguarde a primeira coleta do Edge." /> : (
              <ul className="panel divide-y divide-line">
                {olts.data.map((o) => (
                  <li key={o.id} className="p-3">
                    <div className="font-medium">{o.name}</div>
                    <div className="text-sm text-muted">{o.vendor} {o.model ?? ""} · {o.onu_count} ONUs</div>
                    <div className="mt-1 flex items-center gap-3"><StatusPill value={o.support_level} /><DataFreshness freshness={o.freshness} observedAt={o.observed_at} /></div>
                    <OltQueries oltId={o.id} oltName={o.name} />
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section aria-label="ONUs" className="min-w-0">
            <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">ONUs{serial ? ` · busca “${serial}”` : ""}</h2>
            {onus.data === null ? <ErrorState title="Falha ao carregar ONUs" /> : onus.data.length === 0 ? <EmptyState title="Nenhuma ONU encontrada" hint={serial ? "Confira o serial informado." : undefined} /> : (
              <OnuTable onus={onus.data} oltNames={Object.fromEntries((olts.data ?? []).map((o) => [o.id, o.name]))} />
            )}
          </section>
        </div>
      </AppShell>
    );
  }

  // ---- Gestão de ONUs (ADR-0037, padrão Lovable): matriz de PONs · árvore · lista com filtros · detalhes
  const olts = await apiSafe<Olt[]>(`/v1/olts?limit=${READ_LIMIT}`);
  if (olts.status === 403) return <AppShell active="/rede" user="1"><ErrorState title="Sem permissão" hint="Seu papel não permite ver o inventário." /></AppShell>;
  const list = olts.data ?? [];
  const oltsTruncated = list.length >= READ_LIMIT;   // lista parcial: a ausência de uma OLT aqui não prova que ela não existe
  const bySerial = serialQ !== "";   // busca por serial atravessa as OLTs: sem matriz nem árvore, só o resultado
  const oltAsked = !bySerial && oltParam !== undefined;   // um recorte pedido pela URL: se não existe, a tela diz (nunca cai em outra OLT em silêncio)
  const olt = oltAsked ? list.find((o) => o.id === oltParam && UUID.test(oltParam)) ?? null : list[0] ?? null;
  const ponAsked = !bySerial && ponParam !== undefined;
  const ponValid = ponAsked && PON_RE.test(ponParam);
  if (oltAsked && olt === null && olts.data !== null) {
    return (
      <AppShell active="/rede" user="1">
        <PageHeader title="Rede" subtitle="OLTs, PONs e ONUs com frescor e fonte do dado" helpSlug="rede/consultar-onu" />
        <DevicesTabs current="/rede" />
        <div data-testid="onu-inventory-ready"><EmptyState title="OLT não encontrada" hint={oltsTruncated ? `Não está entre as primeiras ${READ_LIMIT} OLTs lidas; ela pode existir. Use a busca por serial.` : "O link aponta para uma OLT que não existe (ou não existe mais) neste provedor."} /></div>
        <p className="mt-4 text-sm"><Link href="/rede" className="text-accent underline underline-offset-2">Ver todas as OLTs</Link></p>
      </AppShell>
    );
  }
  const onus = await apiSafe<Onu[]>(bySerial ? `/v1/onus?limit=${READ_LIMIT}${serialQ}` : olt ? `/v1/onus?limit=${READ_LIMIT}&olt_id=${olt.id}` : "/v1/onus?limit=1");
  if (onus.status === 403) return <AppShell active="/rede" user="1"><ErrorState title="Sem permissão" hint="Seu papel não permite ver o inventário." /></AppShell>;
  const all = onus.data ?? [];
  const pons = bySerial ? [] : summarizePons(all);
  const pon = ponValid && pons.some((p) => p.path === ponParam) ? ponParam : undefined;   // PON inexistente nesta OLT: mostra a OLT inteira e AVISA
  const ponMissing = ponAsked && !pon && olts.data !== null && onus.data !== null;
  const rows = bySerial || !pon ? all : all.filter((o) => o.pon_path === pon);
  const names = Object.fromEntries(list.map((o) => [o.id, o.name]));
  const truncated = all.length >= READ_LIMIT;
  const title = bySerial ? "Rede" : pon ? `PON ${pon}` : olt?.name ?? "Rede";
  return (
    <AppShell active="/rede" user="1">
      <PageHeader title={title} subtitle={bySerial ? `Busca “${serial}” em todas as OLTs` : "OLTs, PONs e ONUs com frescor e fonte do dado"} helpSlug="rede/consultar-onu">
        {olt && !bySerial && (
          <div className="flex flex-wrap items-center gap-3">
            <StatusPill value={olt.support_level} /><DataFreshness freshness={olt.freshness} observedAt={olt.observed_at} />
            <OltQueries oltId={olt.id} oltName={olt.name} />
          </div>
        )}
      </PageHeader>
      <DevicesTabs current="/rede" />
      {!bySerial && olt && (
        <nav aria-label="Trilha" className="mb-4 flex flex-wrap items-center gap-1 text-sm text-muted" data-testid="rede-breadcrumb">
          <Link href="/rede" className="hover:text-text">Rede</Link><span aria-hidden>›</span>
          {pon ? <Link href={`/rede?olt=${encodeURIComponent(olt.id)}`} className="hover:text-text">{olt.name}</Link> : <span className="text-text">{olt.name}</span>}
          {pon && <><span aria-hidden>›</span><span className="text-text">PON {pon}</span></>}
        </nav>
      )}
      {ponMissing && <p role="status" className="mb-4 rounded-btn bg-warn-soft px-4 py-3 text-sm text-warn" data-testid="pon-missing">A PON pedida no link não tem ONUs nesta OLT (ou o link é inválido). Mostrando a OLT inteira.</p>}
      {oltsTruncated && <p role="status" className="mb-4 rounded-btn bg-warn-soft px-4 py-3 text-sm text-warn" data-testid="olts-truncated">Mostrando as primeiras {READ_LIMIT} OLTs: há mais do que o limite de leitura.</p>}
      {bySerial && <p className="mb-4 text-sm"><Link href="/rede" className="text-accent underline underline-offset-2">Limpar a busca</Link></p>}
      <div data-testid="onu-inventory-ready">
        {olts.data === null ? <ErrorState title="Falha ao carregar OLTs" />
          : list.length === 0 ? <EmptyState title="Nenhuma OLT coletada" hint="Aguarde a primeira coleta do Edge." />
          : onus.data === null ? <ErrorState title="Falha ao carregar ONUs" />
          : (
            <>
              {olt && !bySerial && <PonMatrix oltId={olt.id} oltName={olt.name} model={olt.model} pons={pons} {...(pon ? { activePon: pon } : {})} truncated={truncated} />}
              {truncated && <p role="status" className="mb-3 rounded-btn bg-warn-soft px-4 py-3 text-sm text-warn" data-testid="onu-truncated">Mostrando as primeiras {READ_LIMIT} ONUs: há mais ONUs do que o limite de leitura. Use a busca por serial para as demais.</p>}
              {rows.length === 0 && bySerial ? <EmptyState title="Nenhuma ONU encontrada" hint="Confira o serial informado." /> : (
                <OnuWorkspace key={`${bySerial ? serialQ : ""}|${olt?.id ?? ""}|${pon ?? ""}`} ontConfig={ontConfig} speed={speed} onus={rows} oltNames={names}
                  tree={bySerial || !olt ? undefined : <PonTree olts={list} oltId={olt.id} pons={pons} {...(pon ? { ponId: pon } : {})} />} />
              )}
            </>
          )}
      </div>
    </AppShell>
  );
}
