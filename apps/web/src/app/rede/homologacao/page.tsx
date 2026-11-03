import Link from "next/link";
import { notFound } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { EmptyState, ErrorState, PageHeader } from "@/components/ui";
import { apiSafe } from "@/lib/api";
import { featuresOn } from "@/lib/features";
import { KIND_LABEL, LEVEL_TEXT, ageText, type Homolog } from "@/lib/knowledge";

export default async function Homologacao() {
  if (!(await featuresOn("fleet_manager"))) notFound();   // recurso desligado: a tela não existe
  const r = await apiSafe<Homolog>("/v1/fleet/homologation");
  if (r.status === 403) return <AppShell active="/rede" user="1"><ErrorState title="Sem permissão" hint="Seu papel não permite ver a homologação das OLTs." /></AppShell>;
  const d = r.data;
  return (
    <AppShell active="/rede" user="1">
      <PageHeader title="Homologação das OLTs" subtitle="Até onde cada modelo e firmware está provado. O nível é calculado a partir de evidência; ninguém o digita." helpSlug="rede/homologacao-de-olts">
        <Link href="/rede/frota" className="inline-flex min-h-touch items-center rounded-btn px-3 text-sm text-accent hover:underline">← Frota de OLTs</Link>
      </PageHeader>
      <p role="note" data-testid="hom-aviso" className="mb-4 rounded-btn border border-line bg-surface px-3 py-2 text-sm text-muted">Firmware novo não herda nível: cada linha vale só para o modelo e o firmware exatos. Fixture sintética não conta para nenhum nível. Nenhum equipamento está acima de L2 e nada aqui libera escrita.</p>
      {d === null ? <ErrorState title="Falha ao carregar a homologação" hint={r.status === 503 ? "O livro de evidências falhou na verificação e foi recusado inteiro." : undefined} /> : (
        <div className="grid gap-6">
          <section aria-label="Equipamentos catalogados" data-testid="hom-equipamentos">
            <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">Modelos e firmwares</h2>
            <ul className="grid gap-3">
              {d.devices.map((x) => (
                <li key={`${x.model}-${x.firmware}`} className="panel p-3 text-sm" data-testid="hom-equip" data-level={x.level}>
                  <p className="font-medium">{x.vendor} {x.model} · {x.firmware} <span className="ml-2 rounded-btn border border-accent px-2 py-0.5 text-xs text-accent" data-testid="hom-nivel">{LEVEL_TEXT[x.level] ?? x.level}</span></p>
                  <p className="text-muted">{x.note}</p>
                  <p className="mt-1">Driver do Edge: <strong>{x.driver_level}</strong></p>
                  {x.next_blockers.length > 0 && <div className="mt-1"><p className="text-muted">Para o próximo nível falta:</p><ul className="list-disc pl-5">{x.next_blockers.map((b) => <li key={b}>{b}</li>)}</ul></div>}
                  <details className="mt-2"><summary className="cursor-pointer">Os 22 testes da matriz ({x.coverage.filter((c) => c.kind === "real_fixture").length} com captura real · {x.coverage.filter((c) => c.kind === "unit_test").length} só com teste automatizado)</summary>
                    <table className="mt-2 w-full text-left"><caption className="sr-only">Cobertura dos 22 testes para {x.model}</caption>
                      <thead><tr className="border-b border-line text-muted"><th scope="col" className="p-1">#</th><th scope="col" className="p-1">Teste</th><th scope="col" className="p-1">Evidência</th></tr></thead>
                      <tbody>{x.coverage.map((c) => (<tr key={c.n} className="border-b border-line"><td className="p-1">{c.n}</td><td className="p-1">{c.label}</td><td className="p-1">{KIND_LABEL[c.kind] ?? c.kind}{c.ref ? <span className="block break-all text-xs text-muted">{c.ref}</span> : null}</td></tr>))}</tbody></table>
                  </details>
                </li>))}
            </ul>
          </section>
          <section aria-label="OLTs cadastradas" data-testid="hom-olts">
            <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">OLTs cadastradas</h2>
            {d.olts.length === 0 ? <EmptyState title="Nenhuma OLT cadastrada" /> : (
              <div className="overflow-x-auto"><table className="w-full text-left text-sm"><caption className="sr-only">Nível de cada OLT cadastrada e idade da última leitura</caption>
                <thead><tr className="border-b border-line text-muted"><th scope="col" className="p-2">OLT</th><th scope="col" className="p-2">Modelo e firmware</th><th scope="col" className="p-2">Nível</th><th scope="col" className="p-2">Última leitura</th></tr></thead>
                <tbody>{d.olts.map((o) => (<tr key={o.name} className="border-b border-line" data-testid="hom-olt"><td className="p-2">{o.name}</td><td className="p-2">{o.model ? `${o.vendor} ${o.model} · ${o.firmware ?? "?"}` : "ainda não lida"}</td><td className="p-2">{o.level}</td>
                  <td className="p-2">{ageText(o.age_seconds)}{o.stale ? <span className="ml-2 rounded-btn border border-warn px-2 py-0.5 text-xs" data-testid="hom-stale">desatualizada</span> : <span className="ml-2 rounded-btn border border-ok px-2 py-0.5 text-xs text-ok" data-testid="hom-emdia">em dia</span>}</td></tr>))}</tbody></table></div>)}
            {d.olts_truncated && <p role="status" data-testid="hom-truncada" className="mt-2 text-sm text-warn">Mostrando {d.olts.length} de {d.olts_total} OLTs: a lista foi truncada.</p>}
            <p className="mt-2 text-xs text-muted">Leitura de até {d.stale_after_minutes} min aparece como em dia; acima disso, ou nunca lida, aparece como desatualizada.</p>
          </section>
          <section aria-label="Testes de conexão" data-testid="hom-testes" className="panel p-3 text-sm">
            <h2 className="mb-1 text-sm font-semibold uppercase tracking-wide text-muted">Testes de conexão nas últimas 24 h</h2>
            {Object.keys(d.connection_tests_24h).length === 0 ? <p className="text-muted">Nenhum teste pedido.</p> : <p>{Object.entries(d.connection_tests_24h).map(([k, v]) => `${k}: ${v}`).join(" · ")}</p>}
          </section>
          <section aria-label="Níveis" className="text-sm text-muted" data-testid="hom-legenda"><h2 className="mb-1 text-sm font-semibold uppercase tracking-wide">Níveis</h2><ul className="list-disc pl-5">{d.levels.map((l) => <li key={l}>{LEVEL_TEXT[l] ?? l}</li>)}</ul></section>
        </div>)}
    </AppShell>
  );
}
