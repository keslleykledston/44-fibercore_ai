import Link from "next/link";
import { notFound } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { EmptyState, ErrorState, PageHeader } from "@/components/ui";
import { apiSafe } from "@/lib/api";
import { featuresOn } from "@/lib/features";
import { FRESH_LABEL, SOURCE_LABEL, UUID, FIELD_LABEL, type Draft, type ProfileList } from "@/lib/profiles";
import type { Olt } from "@/lib/types";

const FLASH: Record<string, string> = {
  importado: "Perfil importado como instantâneo (imutável).", invalido: "Dados inválidos: confira os campos e o JSON.", permissao: "Seu papel não permite esta ação.",
  identidade: "A OLT ainda não tem fabricante, modelo e firmware identificados.",
  semleitura: "Ainda não há leitura dos perfis DBA desta OLT. Peça a consulta “Perfis DBA” em Rede → Consultas da OLT e tente de novo.",
  leituraantiga: "A última leitura dos perfis DBA tem mais de 24 h. Peça a consulta de novo antes de atualizar.",
  maisnova: "Uma leitura mais nova desta OLT já foi aplicada; esta ficou para trás e não foi usada.", falha: "Não foi possível concluir. Tente novamente.",
};
const field = "min-h-touch rounded-btn border border-line bg-bg px-3";

export default async function Perfis({ searchParams }: { searchParams: Promise<{ olt?: string; ok?: string; erro?: string; n?: string; u?: string; a?: string }> }) {
  if (!(await featuresOn("profile_studio"))) notFound();   // recurso desligado: a tela não existe (ADR-0040)
  const { olt: oltParam, ok, erro, n, u, a } = await searchParams;
  const olts = await apiSafe<Olt[]>("/v1/olts?limit=200");
  if (olts.status === 403) return <AppShell active="/rede" user="1"><ErrorState title="Sem permissão" hint="Seu papel não permite ver o inventário." /></AppShell>;
  const list = olts.data ?? [];
  const sel = list.find((o) => o.id === oltParam && UUID.test(o.id)) ?? list[0];
  const [profiles, drafts] = await Promise.all([sel ? apiSafe<ProfileList>(`/v1/olts/${sel.id}/profiles`) : null, apiSafe<{ items: Draft[] }>("/v1/profile-drafts")]);
  if (profiles?.status === 403 || drafts.status === 403) return <AppShell active="/rede" user="1"><ErrorState title="Sem permissão" hint="Seu papel não permite ver os perfis da OLT." /></AppShell>;
  const num = (v?: string) => (v && /^[0-9]{1,3}$/.test(v) ? Number(v) : 0);
  const msg = ok === "sincronizado" ? `Perfis DBA atualizados a partir da última leitura: ${num(n)} novo(s), ${num(u)} sem mudança, ${num(a)} ausente(s) da leitura.` : ok ? FLASH[ok] : erro ? FLASH[erro] : null;
  return (
    <AppShell active="/rede" user="1">
      <PageHeader title="Perfis da OLT" subtitle="Inventário, rascunhos e simulação. Nada aqui altera a OLT." helpSlug="rede/perfis-olt">
        <Link href="/rede" className="inline-flex min-h-touch items-center rounded-btn px-3 text-sm text-accent hover:underline">← Voltar para Rede</Link>
      </PageHeader>
      {msg && <p role={erro ? "alert" : "status"} data-testid="perfis-flash" className={`mb-4 rounded-btn border px-3 py-2 text-sm ${erro ? "border-danger text-danger" : "border-ok text-ok"}`}>{msg}</p>}
      {list.length === 0 ? <EmptyState title="Nenhuma OLT cadastrada" hint="Os perfis aparecem depois que o Edge informa uma OLT." /> : (
        <div className="grid gap-4">
          <nav aria-label="OLTs" className="flex flex-wrap gap-2">
            {list.map((o) => <Link key={o.id} href={`/rede/perfis?olt=${o.id}`} aria-current={o.id === sel?.id ? "page" : undefined} data-testid="perfis-olt"
              className={`inline-flex min-h-touch items-center rounded-btn border px-3 text-sm ${o.id === sel?.id ? "border-accent bg-accent-soft font-semibold" : "border-line hover:bg-bg"}`}>{o.name}</Link>)}
          </nav>
          {sel && profiles?.data && (
            <section aria-label="Perfis observados" data-testid="perfis-inventario" className="panel p-4">
              <h2 className="mb-1 text-sm font-semibold uppercase tracking-wide text-muted">Perfis observados em {profiles.data.olt_name}</h2>
              <p data-testid="perfis-cert" className={`mb-3 text-sm ${profiles.data.driver_read_certified ? "text-ok" : "text-warn"}`}>
                {profiles.data.driver_read_certified ? "▲ Leitura de perfis certificada para este modelo e firmware." : "○ Leitura de perfis ainda NÃO certificada para este modelo e firmware: as comparações ficam como “sem leitura certificada”."}
              </p>
              <form method="post" action="/bff/perfis/sincronizar" className="mb-3 flex flex-wrap items-center gap-3">
                <input type="hidden" name="olt" value={sel.id} />
                <button type="submit" data-testid="perfis-sincronizar" className="min-h-touch rounded-btn border border-line px-4 text-sm hover:bg-bg">Atualizar a partir da última leitura (perfis DBA)</button>
                <span className="text-xs text-muted">Usa a leitura que o Edge já fez; não pergunta nada à OLT. Fica parcial: só o que a leitura afirma.</span>
              </form>
              {profiles.data.items.length === 0 ? <EmptyState title="Nenhum perfil importado para esta OLT" hint="Use “Importar perfil” abaixo. A leitura direta da OLT só entra após captura supervisionada." /> : (
                <div className="overflow-x-auto"><table className="w-full text-sm">
                  <caption className="sr-only">Perfis observados na OLT</caption>
                  <thead><tr className="text-left text-xs text-muted"><th scope="col" className="py-1 pr-3">Perfil</th><th scope="col" className="pr-3">Placa PON</th><th scope="col" className="pr-3">Origem</th><th scope="col" className="pr-3">Situação</th><th scope="col" className="pr-3">Em uso</th><th scope="col">Rascunho</th></tr></thead>
                  <tbody>{profiles.data.items.map((s) => (
                    <tr key={s.id} data-testid="perfis-linha" className="border-t border-line align-top">
                      <td className="py-2 pr-3"><span className="font-mono">{s.native_key}</span><span className="block text-xs text-muted">{s.native_type} · {s.technology.toUpperCase()} · {s.vendor} {s.model} {s.firmware}</span></td>
                      <td className="pr-3">{s.pon_card}</td>
                      <td className="pr-3">{SOURCE_LABEL[s.source] ?? s.source}{!s.authoritative && <span className="block text-xs text-warn">não vale como leitura da OLT</span>}</td>
                      <td className="pr-3">{FRESH_LABEL[s.freshness]}{s.completeness !== "complete" && <span className="block text-xs text-warn">leitura {s.completeness === "partial" ? "parcial" : "sem garantia"}</span>}</td>
                      <td className="pr-3">{s.reference_count ?? "—"}</td>
                      <td>
                        <details><summary className="cursor-pointer text-accent">Criar rascunho</summary>
                          <form method="post" action="/bff/perfis/rascunhos" className="mt-2 grid gap-2">
                            <input type="hidden" name="snapshot" value={s.id} /><input type="hidden" name="olt" value={sel.id} />
                            <label className="grid gap-1 text-xs">Nome do rascunho<input name="name" required maxLength={80} defaultValue={`${s.native_key} (cópia)`} className={field} /></label>
                            <label className="grid gap-1 text-xs">Motivo<input name="reason" required maxLength={300} className={field} /></label>
                            <button type="submit" className="min-h-touch rounded-btn border border-line px-3 hover:bg-bg">Criar cópia editável</button>
                          </form>
                        </details>
                      </td>
                    </tr>))}</tbody>
                </table></div>
              )}
            </section>
          )}
          {sel && (
            <details className="panel p-4" data-testid="perfis-importar">
              <summary className="cursor-pointer text-sm font-semibold uppercase tracking-wide text-muted">Importar perfil (à mão)</summary>
              <form method="post" action="/bff/perfis/importar" className="mt-3 grid gap-3 sm:grid-cols-2">
                <input type="hidden" name="olt" value={sel.id} />
                <label className="grid gap-1 text-sm">Tipo nativo<input name="native_type" required defaultValue="line" pattern="[a-z][a-z0-9_-]{1,39}" className={field} /></label>
                <label className="grid gap-1 text-sm">Nome/ID na OLT<input name="native_key" required maxLength={80} className={field} /></label>
                <label className="grid gap-1 text-sm">Tecnologia<select name="technology" className={field}><option value="gpon">GPON</option><option value="xgspon">XGS-PON</option><option value="epon">EPON</option></select></label>
                <label className="grid gap-1 text-sm">Placa PON<input name="pon_card" required maxLength={60} className={field} /></label>
                <label className="grid gap-1 text-sm">Leitura<select name="completeness" className={field}><option value="complete">Completa</option><option value="partial">Parcial</option><option value="unknown">Sem garantia</option></select></label>
                <label className="grid gap-1 text-sm">Observado em (UTC, vazio = agora)<input name="observed_at" type="datetime-local" className={field} /></label>
                <label className="grid gap-1 text-sm sm:col-span-2">Campos do perfil (JSON tipado)
                  <textarea name="settings" required rows={6} defaultValue={'{\n  "dba_type": "type4",\n  "maximum_kbps": 1000000\n}'} spellCheck={false} className="rounded-btn border border-line bg-bg p-3 font-mono text-xs" /></label>
                <p className="text-xs text-muted sm:col-span-2">Campos aceitos: {Object.values(FIELD_LABEL).join(", ")}. Comandos de CLI e segredos são recusados. Importação manual nunca conta como leitura autoritativa da OLT.</p>
                <button type="submit" className="min-h-touch rounded-btn bg-accent px-4 font-semibold text-white sm:col-span-2">Importar instantâneo</button>
              </form>
            </details>
          )}
          <section aria-label="Rascunhos" data-testid="perfis-rascunhos" className="panel p-4">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted">Rascunhos</h2>
            {(drafts.data?.items.length ?? 0) === 0 ? <EmptyState title="Nenhum rascunho" hint="Crie um a partir de um perfil observado." /> : (
              <ul className="grid gap-2">{drafts.data!.items.map((d) => (
                <li key={d.id} className="flex flex-wrap items-baseline justify-between gap-2 border-t border-line pt-2 first:border-0 first:pt-0">
                  <Link href={`/rede/perfis/${d.id}`} data-testid="perfis-rascunho" className="font-semibold text-accent hover:underline">{d.name}</Link>
                  <span className="text-xs text-muted">{d.scope.vendor} {d.scope.model} · {d.scope.firmware} · revisão {d.row_version} · {Object.keys(d.desired).length} campos</span>
                </li>))}</ul>
            )}
          </section>
        </div>
      )}
    </AppShell>
  );
}
