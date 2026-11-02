import Link from "next/link";
import { notFound } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { EmptyState, ErrorState, PageHeader } from "@/components/ui";
import { apiPost, apiSafe } from "@/lib/api";
import { featuresOn } from "@/lib/features";
import {
  BLOCKER_LABEL, DIFF_LABEL, FIELD_LABEL, FRESH_LABEL, issueText, LIST_FIELDS, REASON_LABEL, SCALAR_NUM, SHAPING, STRATEGY_LABEL, TAGGING, UUID,
  type Compare, type Draft, type DryRun, type ProfileList, type Snapshot,
} from "@/lib/profiles";
import type { Olt } from "@/lib/types";

const FLASH: Record<string, string> = {
  salvo: "Rascunho salvo.", invalido: "Não salvei: algum campo não cabe no modelo tipado (ou o JSON está inválido).", permissao: "Seu papel não permite esta ação.",
  versao: "Outra pessoa salvou este rascunho antes. Recarregue e refaça a edição: nada foi sobrescrito.", semalvo: "Defina ao menos uma OLT alvo antes de simular.", falha: "Não foi possível concluir. Tente novamente.",
};
const field = "min-h-touch rounded-btn border border-line bg-bg px-3";
const DIFF_CLS: Record<string, string> = { EQUAL: "text-ok", CHANGE: "text-warn", ADD: "text-warn", REMOVE: "text-warn", NOT_OBSERVABLE: "text-muted", UNSUPPORTED: "text-muted", CONFLICT: "text-danger" };
const DIFF_MARK: Record<string, string> = { EQUAL: "●", CHANGE: "▲", ADD: "+", REMOVE: "−", NOT_OBSERVABLE: "○", UNSUPPORTED: "○", CONFLICT: "▲" };
const show = (v: unknown) => (v === undefined ? "—" : typeof v === "string" ? v : JSON.stringify(v));

export default async function Rascunho({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ ok?: string; erro?: string; aba?: string; comparar?: string; run?: string }> }) {
  if (!(await featuresOn("profile_studio"))) notFound();
  const { id } = await params;
  const { ok, erro, aba, comparar, run } = await searchParams;
  if (!UUID.test(id)) notFound();
  const d = await apiSafe<Draft>(`/v1/profile-drafts/${id}`);
  if (d.status === 404) notFound();
  if (d.status === 403) return <AppShell active="/rede" user="1"><ErrorState title="Sem permissão" hint="Seu papel não permite ver os perfis da OLT." /></AppShell>;
  const draft = d.data;
  if (!draft) return <AppShell active="/rede" user="1"><ErrorState title="Falha ao carregar o rascunho" hint="Tente novamente em instantes." /></AppShell>;

  // Instantâneos candidatos à comparação: os perfis observados nas OLTs alvo.
  const targets = await Promise.all(draft.target_olt_ids.map((o) => apiSafe<ProfileList>(`/v1/olts/${o}/profiles`)));
  const olts = await apiSafe<Olt[]>("/v1/olts?limit=200");
  const oltName = (oid: string) => olts.data?.find((o) => o.id === oid)?.name ?? "OLT";
  const snaps: (Snapshot & { olt_name: string })[] = targets.flatMap((t) => (t.data?.items ?? []).map((s) => ({ ...s, olt_name: t.data!.olt_name })));
  const chosen = comparar && UUID.test(comparar) ? snaps.find((s) => s.id === comparar) : undefined;
  const cmp = chosen ? await apiPost(`/v1/profile-drafts/${id}/compare`, JSON.stringify({ snapshot_id: chosen.id }), { "Content-Type": "application/json" }) : null;   // leitura pura (POST só carrega o corpo)
  const compare = cmp?.status === 200 ? (cmp.json as Compare) : null;
  const dr = run && UUID.test(run) ? await apiSafe<DryRun>(`/v1/profile-dry-runs/${run}`) : null;

  const expert = aba === "especialista";
  const dz = draft.desired as Record<string, unknown>;
  const tab = (key: string, label: string, on: boolean) => <Link href={`/rede/perfis/${id}?aba=${key}`} role="tab" aria-selected={on} data-testid={`perfis-aba-${key}`}
    className={`inline-flex min-h-touch items-center rounded-btn border px-3 text-sm ${on ? "border-accent bg-accent-soft font-semibold" : "border-line hover:bg-bg"}`}>{label}</Link>;
  const msg = ok ? FLASH[ok] : erro ? FLASH[erro] : null;
  const hidden = <><input type="hidden" name="version" value={draft.row_version} /><input type="hidden" name="mode" value={expert ? "json" : "form"} /></>;

  return (
    <AppShell active="/rede" user="1">
      <PageHeader title={draft.name} subtitle={`Rascunho · ${draft.scope.vendor} ${draft.scope.model} · firmware ${draft.scope.firmware} · revisão ${draft.row_version}`} helpSlug="rede/perfis-olt">
        <Link href="/rede/perfis" className="inline-flex min-h-touch items-center rounded-btn px-3 text-sm text-accent hover:underline">← Voltar para Perfis</Link>
      </PageHeader>
      {msg && <p role={erro ? "alert" : "status"} data-testid="perfis-flash" className={`mb-4 rounded-btn border px-3 py-2 text-sm ${erro ? "border-danger text-danger" : "border-ok text-ok"}`}>{msg}</p>}
      <p data-testid="perfis-aviso" className="mb-4 rounded-btn border border-line px-3 py-2 text-sm text-muted">Este rascunho é uma cópia. Salvar e simular <strong>não alteram a OLT</strong>; a aplicação em equipamento não existe nesta versão.</p>
      <div className="grid gap-4">
        <section aria-label="Editor" className="panel p-4" data-testid="perfis-editor">
          <div role="tablist" aria-label="Modo de edição" className="mb-3 flex gap-2">{tab("assistido", "Assistido (formulário)", !expert)}{tab("especialista", "Especialista (JSON)", expert)}</div>
          {expert ? (
            <form method="post" action={`/bff/perfis/rascunhos/${id}/salvar`} className="grid gap-3">
              {hidden}
              <label className="grid gap-1 text-sm">Campos desejados (JSON tipado; comandos de CLI e segredos são recusados)
                <textarea name="desired_json" rows={14} defaultValue={JSON.stringify(dz, null, 2)} spellCheck={false} data-testid="perfis-json" className="rounded-btn border border-line bg-bg p-3 font-mono text-xs" /></label>
              <button type="submit" className="min-h-touch rounded-btn bg-accent px-4 font-semibold text-white">Salvar rascunho</button>
            </form>
          ) : (
            <form method="post" action={`/bff/perfis/rascunhos/${id}/salvar`} className="grid gap-3 sm:grid-cols-2">
              {hidden}
              <label className="grid gap-1 text-sm">Nome<input name="name" defaultValue={draft.name} maxLength={80} className={field} /></label>
              <label className="grid gap-1 text-sm">Motivo<input name="reason" defaultValue={draft.reason} maxLength={300} className={field} /></label>
              <label className="grid gap-1 text-sm">{FIELD_LABEL.dba_type}<input name="dba_type" defaultValue={show(dz.dba_type) === "—" ? "" : String(dz.dba_type)} maxLength={64} className={field} /></label>
              {SCALAR_NUM.map((k) => <label key={k} className="grid gap-1 text-sm">{FIELD_LABEL[k]}<input name={k} inputMode="numeric" pattern="[0-9]*" defaultValue={dz[k] === undefined ? "" : String(dz[k])} className={field} /></label>)}
              <label className="grid gap-1 text-sm">{FIELD_LABEL.tagging}<select name="tagging" defaultValue={String(dz.tagging ?? "")} className={field}><option value="">(não definir)</option>{TAGGING.map((t) => <option key={t}>{t}</option>)}</select></label>
              <label className="grid gap-1 text-sm">{FIELD_LABEL.shaping_owner}<select name="shaping_owner" defaultValue={String(dz.shaping_owner ?? "")} className={field}><option value="">(não definir)</option>{SHAPING.map((t) => <option key={t}>{t}</option>)}</select></label>
              <label className="grid gap-1 text-sm">{FIELD_LABEL.multicast}<select name="multicast" defaultValue={dz.multicast === undefined ? "" : String(dz.multicast)} className={field}><option value="">(não definir)</option><option value="true">Ligado</option><option value="false">Desligado</option></select></label>
              <label className="grid gap-1 text-sm sm:col-span-2">{FIELD_LABEL.description}<input name="description" defaultValue={dz.description === undefined ? "" : String(dz.description)} maxLength={256} className={field} /></label>
              {LIST_FIELDS.map((k) => <label key={k} className="grid gap-1 text-sm sm:col-span-2">{FIELD_LABEL[k]} (lista JSON)
                <textarea name={k} rows={3} defaultValue={dz[k] === undefined ? "" : JSON.stringify(dz[k])} spellCheck={false} className="rounded-btn border border-line bg-bg p-3 font-mono text-xs" /></label>)}
              <button type="submit" className="min-h-touch rounded-btn bg-accent px-4 font-semibold text-white sm:col-span-2">Salvar rascunho</button>
            </form>
          )}
        </section>

        <section aria-label="Comparação" className="panel p-4" data-testid="perfis-comparar">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted">Comparar com o que a OLT tem</h2>
          {snaps.length === 0 ? <EmptyState title="Sem perfis observados nas OLTs alvo" hint="Importe um perfil na OLT alvo para comparar." /> : (
            <form method="get" className="mb-3 flex flex-wrap items-end gap-2">
              {aba && <input type="hidden" name="aba" value={aba} />}
              <label className="grid gap-1 text-sm">Perfil observado
                <select name="comparar" defaultValue={chosen?.id ?? ""} className={field}>{snaps.map((s) => <option key={s.id} value={s.id}>{s.olt_name} · {s.native_key} ({FRESH_LABEL[s.freshness]})</option>)}</select></label>
              <button type="submit" className="min-h-touch rounded-btn border border-line px-4 hover:bg-bg">Comparar</button>
            </form>
          )}
          {cmp && !compare && <ErrorState title="Não consegui comparar" hint="Tente novamente em instantes." />}
          {compare && (
            <div data-testid="perfis-diff">
              <p data-testid="perfis-equivalente" className={`mb-2 text-sm font-semibold ${compare.equivalent ? "text-ok" : "text-warn"}`}>{compare.equivalent ? "● Equivalente ao perfil observado." : "▲ Não dá para afirmar equivalência."}</p>
              {compare.blockers.length > 0 && <ul className="mb-3 list-disc pl-5 text-sm text-muted" data-testid="perfis-bloqueios">{compare.blockers.map((b) => <li key={b}>{BLOCKER_LABEL[b] ?? b}</li>)}</ul>}
              <div className="overflow-x-auto"><table className="w-full text-sm">
                <caption className="sr-only">Diferença campo a campo</caption>
                <thead><tr className="text-left text-xs text-muted"><th scope="col" className="py-1 pr-3">Campo</th><th scope="col" className="pr-3">Rascunho</th><th scope="col" className="pr-3">Na OLT</th><th scope="col">Resultado</th></tr></thead>
                <tbody>{Object.entries(compare.diff).map(([k, v]) => (
                  <tr key={k} className="border-t border-line" data-testid="perfis-diff-linha">
                    <th scope="row" className="py-1 pr-3 text-left font-normal">{FIELD_LABEL[k] ?? k}</th><td className="pr-3 font-mono text-xs">{show(dz[k])}</td><td className="pr-3 font-mono text-xs">{show(chosen?.settings[k])}</td>
                    <td className={DIFF_CLS[v]}><span aria-hidden>{DIFF_MARK[v]} </span>{DIFF_LABEL[v] ?? v}</td>
                  </tr>))}</tbody>
              </table></div>
              {compare.issues.length > 0 && <ul className="mt-2 list-disc pl-5 text-xs text-muted">{compare.issues.map((i) => <li key={`${i.field}-${i.code}`}>{issueText(i)}</li>)}</ul>}
            </div>
          )}
        </section>

        <section aria-label="Simulação" className="panel p-4" data-testid="perfis-simulacao">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted">Simulação (dry-run)</h2>
          <form method="post" action={`/bff/perfis/rascunhos/${id}/simular`} className="mb-3">
            <button type="submit" data-testid="perfis-simular" className="min-h-touch rounded-btn border border-line px-4 hover:bg-bg">Simular nas OLTs alvo</button>
            <span className="ml-3 text-xs text-muted">Alvos: {draft.target_olt_ids.length ? draft.target_olt_ids.map(oltName).join(", ") : "nenhum"}</span>
          </form>
          {dr?.data && (
            <div data-testid="perfis-resultado">
              <p className="mb-2 text-sm" data-testid="perfis-sem-escrita">Escritas na OLT: <strong>{dr.data.writes}</strong> · {dr.data.executable ? "executável" : "não executável (somente simulação)"} · {dr.data.reproducible ? "reproduzível" : "NÃO reproduzível"} · {dr.data.expired ? "expirada" : <>válida até <span data-testid="volatile">{new Date(dr.data.expires_at).toLocaleTimeString("pt-BR", { timeStyle: "short" })}</span></>}</p>
              <ul className="grid gap-2">{dr.data.plans.map((p) => (
                <li key={p.olt_id} className="rounded-btn border border-line p-3 text-sm" data-testid="perfis-plano">
                  <p className="font-semibold">{oltName(p.olt_id)} — {STRATEGY_LABEL[p.strategy] ?? p.strategy}</p>
                  <p className="text-xs text-muted">{REASON_LABEL[p.reason] ?? p.reason}{p.reference_count != null ? ` · ${p.reference_count} ONU(s) usam o perfil de origem` : ""}</p>
                  {p.changed_fields.length > 0 && <p className="text-xs">Mudaria: {p.changed_fields.map((f) => FIELD_LABEL[f] ?? f).join(", ")}</p>}
                  <p data-testid="volatile" className="mt-1 font-mono text-[11px] text-muted">plano {p.plan_hash.slice(0, 16)}…</p>
                </li>))}</ul>
              {dr.data.issues.length > 0 && <ul className="mt-2 list-disc pl-5 text-xs text-muted">{dr.data.issues.map((i) => <li key={`${i.field}-${i.code}`}>{issueText(i)}</li>)}</ul>}
            </div>
          )}
        </section>
      </div>
    </AppShell>
  );
}
