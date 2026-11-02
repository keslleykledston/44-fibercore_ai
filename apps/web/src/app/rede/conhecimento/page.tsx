import Link from "next/link";
import { notFound } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { EmptyState, ErrorState, PageHeader } from "@/components/ui";
import { apiSafe } from "@/lib/api";
import { featuresOn } from "@/lib/features";
import { KB_WARNING, RECIPE_STATUS_LABEL, RISK_LABEL, SECTIONS, safeUrl, type Command, type Intent, type MatrixRow, type Recipe, type SectionId, type Source } from "@/lib/knowledge";

type Items<T> = { items: T[] };

export default async function Conhecimento({ searchParams }: { searchParams: Promise<{ secao?: string | string[]; vendor?: string | string[] }> }) {
  if (!(await featuresOn("fleet_manager"))) notFound();   // recurso desligado: a tela não existe
  const sp = await searchParams;
  const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v) ?? "";
  const sec = SECTIONS.find((s) => s.id === one(sp.secao)) ?? SECTIONS[0];
  const r = await apiSafe<Record<string, unknown>>(`/v1/knowledge/${sec.api}`);
  if (r.status === 403) return <AppShell active="/rede" user="1"><ErrorState title="Sem permissão" hint="Seu papel não permite ver a base de conhecimento." /></AppShell>;
  const d = r.data;
  const vendors = d && Array.isArray((d as Items<{ vendor: string }>).items) ? [...new Set((d as Items<{ vendor: string }>).items.map((x) => String(x.vendor ?? "").toLowerCase()).filter(Boolean))].sort() : [];
  const vendor = vendors.includes(one(sp.vendor).toLowerCase()) ? one(sp.vendor).toLowerCase() : "";
  const keep = <T extends { vendor?: string }>(xs: T[]) => (vendor ? xs.filter((x) => String(x.vendor ?? "").toLowerCase() === vendor) : xs);
  return (
    <AppShell active="/rede" user="1">
      <PageHeader title="Base de conhecimento" subtitle="Fontes, consultas e runbooks de cada fabricante de OLT. Somente leitura: nada aqui é enviado a uma OLT." helpSlug="rede/base-de-conhecimento">
        <Link href="/rede/frota" className="inline-flex min-h-touch items-center rounded-btn px-3 text-sm text-accent hover:underline">← Frota de OLTs</Link>
      </PageHeader>
      <p role="note" data-testid="kb-aviso" className="mb-4 rounded-btn border border-line bg-surface px-3 py-2 text-sm text-muted">{KB_WARNING}</p>
      <nav aria-label="Seções" className="mb-4 flex flex-wrap gap-2" data-testid="kb-secoes">
        {SECTIONS.map((s) => (
          <Link key={s.id} href={`/rede/conhecimento?secao=${s.id}`} aria-current={s.id === sec.id ? "page" : undefined}
            className={`inline-flex min-h-touch items-center rounded-btn border px-3 text-sm ${s.id === sec.id ? "border-accent text-accent" : "border-line hover:bg-bg"}`}>{s.label}</Link>))}
      </nav>
      {vendors.length > 1 && (
        <form method="get" className="mb-4 flex flex-wrap items-end gap-2" data-testid="kb-filtro">
          <input type="hidden" name="secao" value={sec.id} />
          <label className="grid gap-1 text-sm">Fabricante
            <select name="vendor" defaultValue={vendor} className="min-h-touch rounded-btn border border-line bg-bg px-3"><option value="">Todos</option>{vendors.map((v) => <option key={v} value={v}>{v}</option>)}</select></label>
          <button type="submit" className="min-h-touch rounded-btn border border-line px-3 text-sm hover:bg-bg">Filtrar</button>
        </form>)}
      {d === null ? <ErrorState title="Falha ao carregar a base" hint={r.status === 503 ? "A base de conhecimento falhou na verificação de segurança e foi recusada inteira." : undefined} /> : <Section id={sec.id} d={d} keep={keep} />}
    </AppShell>
  );
}

function Empty() { return <EmptyState title="Nada para este filtro" />; }

function Section({ id, d, keep }: { id: SectionId; d: Record<string, unknown>; keep: <T extends { vendor?: string }>(xs: T[]) => T[] }) {
  if (id === "fontes") {
    const xs = keep((d as unknown as Items<Source>).items);
    return xs.length === 0 ? <Empty /> : (
      <ul className="grid gap-3 md:grid-cols-2" data-testid="kb-fontes">
        {xs.map((s) => { const u = safeUrl(s.url); return (
          <li key={s.id} className="panel p-3 text-sm" data-testid="kb-fonte">
            <p className="font-medium"><span className="text-muted">{s.id}</span> · {s.title}</p>
            <p className="text-muted">{s.vendor} {s.family} · autoridade: {s.authority} · {s.topic}</p>
            <p className="mt-1 text-xs text-muted">Ressalva: {s.caveat}</p>
            {u ? <a href={u} target="_blank" rel="noopener noreferrer" className="mt-1 inline-block text-accent hover:underline">Abrir a fonte (site externo)</a> : <span className="text-xs text-muted">link indisponível</span>}
          </li>); })}
      </ul>);
  }
  if (id === "comandos") {
    const xs = keep((d as unknown as Items<Command>).items);
    return xs.length === 0 ? <Empty /> : (
      <div className="overflow-x-auto" data-testid="kb-comandos">
        <table className="w-full text-left text-sm"><caption className="sr-only">Consultas documentadas por fabricante. Nenhuma é executável.</caption>
          <thead><tr className="border-b border-line text-muted"><th scope="col" className="p-2">Fabricante</th><th scope="col" className="p-2">Sintaxe documentada</th><th scope="col" className="p-2">Para quê</th><th scope="col" className="p-2">Risco</th><th scope="col" className="p-2">Situação</th><th scope="col" className="p-2">Fontes</th></tr></thead>
          <tbody>{xs.map((c) => (
            <tr key={c.id} className="border-b border-line align-top" data-testid="kb-comando">
              <td className="p-2">{c.vendor} {c.family}</td><td className="p-2"><code>{c.syntax}</code></td><td className="p-2">{c.purpose}{c.notes ? <span className="block text-xs text-muted">{c.notes}</span> : null}</td>
              <td className="p-2">{RISK_LABEL[c.risk] ?? c.risk}</td><td className="p-2">Documentada · não verificada · não executável</td><td className="p-2">{c.source_ids.join(", ")}</td>
            </tr>))}</tbody></table>
      </div>);
  }
  if (id === "runbooks") {
    const xs = keep((d as unknown as Items<{ vendor: string; text: string }>).items);
    return xs.length === 0 ? <Empty /> : (
      <div className="grid gap-4" data-testid="kb-runbooks">
        {xs.map((r) => (<details key={r.vendor} className="panel p-3" data-testid="kb-runbook"><summary className="cursor-pointer font-medium">{r.vendor}</summary><pre className="mt-2 whitespace-pre-wrap break-words font-sans text-sm">{r.text}</pre></details>))}
      </div>);
  }
  if (id === "intents") {
    const x = d as unknown as Items<Intent> & { note: string; state: string };
    return (
      <div data-testid="kb-intents">
        <p className="mb-3 text-sm text-muted">Estado: <strong>apenas desenho</strong>. {x.note} O Profile Studio existente é quem prepara rascunho e simulação; aqui nada é aplicado.</p>
        <ul className="grid gap-3 md:grid-cols-2">{x.items.map((i) => (
          <li key={i.id} className="panel p-3 text-sm" data-testid="kb-intent"><p className="font-medium">{i.label}</p>
            <p className="text-muted">ONU: {i.onu_mode} · VLAN: {i.vlan_mode}</p><p className="mt-1">Parâmetros: {i.parameters.join(", ")}</p><p>Testes exigidos: {i.required_tests.join(", ")}</p></li>))}</ul>
        <p className="mt-3 text-sm"><Link href="/rede/perfis" className="text-accent hover:underline">Abrir os perfis da OLT (Profile Studio)</Link></p>
      </div>);
  }
  if (id === "receitas") {
    const xs = keep((d as unknown as Items<Recipe>).items);
    return xs.length === 0 ? <Empty /> : (
      <div className="grid gap-4" data-testid="kb-receitas">
        {xs.map((r) => (
          <section key={r.vendor} className="panel p-3 text-sm" data-testid="kb-receita" aria-label={`Receita ${r.vendor}`}>
            <p className="font-medium">{r.vendor} {r.family} <span className="ml-2 rounded-btn border border-line px-2 py-0.5 text-xs">{RECIPE_STATUS_LABEL[r.status] ?? r.status}</span></p>
            <p className="mt-1 text-xs text-muted">Só as etapas de leitura, verificação e pré-visualização aparecem aqui. As etapas de alteração ficam fora desta base: exigem driver homologado, pré-visualização, aprovação e o Profile Studio. O FiberCore não executa nem recomenda estes passos.</p>
            <ol className="mt-2 list-decimal pl-5">{r.steps.map((s) => <li key={s}>{s}</li>)}</ol>
            {r.omitted_change_steps > 0 && <p className="mt-1 text-xs text-muted" data-testid="kb-omitidas">{r.omitted_change_steps} {r.omitted_change_steps === 1 ? "etapa de alteração omitida" : "etapas de alteração omitidas"} (fora desta base).</p>}
            {r.restrictions.length > 0 && <p className="mt-2 text-xs text-muted">Restrições: {r.restrictions.join(" · ")}</p>}
          </section>))}
      </div>);
  }
  const h = d as unknown as { status: string; matrix: MatrixRow[]; playbook: string };
  const rows = keep(h.matrix);
  return (
    <div data-testid="kb-homologacao">
      <p className="mb-3 text-sm text-muted">Situação: <strong>{h.status === "none_vendor_certified_by_this_research" ? "nenhum fabricante certificado por esta pesquisa" : h.status}</strong>. Escrita fica bloqueada por padrão e exige aprovação.</p>
      {rows.length === 0 ? <Empty /> : (
        <div className="overflow-x-auto"><table className="w-full text-left text-sm"><caption className="sr-only">Matriz de homologação por fabricante</caption>
          <thead><tr className="border-b border-line text-muted"><th scope="col" className="p-2">Fabricante</th><th scope="col" className="p-2">Identidade</th><th scope="col" className="p-2">Chassi</th><th scope="col" className="p-2">PON</th><th scope="col" className="p-2">Contagem de ONUs</th><th scope="col" className="p-2">Alarmes</th><th scope="col" className="p-2">Aplicar perfil</th><th scope="col" className="p-2">Evidência</th></tr></thead>
          <tbody>{rows.map((m) => (<tr key={m.vendor} className="border-b border-line" data-testid="kb-matriz-linha"><td className="p-2">{m.vendor}</td><td className="p-2">{m.read_identity}</td><td className="p-2">{m.read_chassis}</td><td className="p-2">{m.read_pon}</td><td className="p-2">{m.read_onu_counts}</td><td className="p-2">{m.read_alarms}</td><td className="p-2">{m.profile_apply}</td><td className="p-2">{m.evidence}</td></tr>))}</tbody></table></div>)}
      <details className="panel mt-4 p-3"><summary className="cursor-pointer font-medium">Roteiro de homologação</summary><pre className="mt-2 whitespace-pre-wrap break-words font-sans text-sm">{h.playbook}</pre></details>
    </div>);
}
