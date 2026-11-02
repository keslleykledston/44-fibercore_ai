import Link from "next/link";
import { notFound } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { EmptyState, ErrorState, PageHeader } from "@/components/ui";
import { apiSafe } from "@/lib/api";
import { ASSOC_LABEL, CONDITION_CLS, CONDITION_LABEL, CONDITION_MARK, FILTERS, REASON_LABEL, SOURCE_LABEL, type PendingList } from "@/lib/discovery";
import { featuresOn } from "@/lib/features";
import { UUID } from "@/lib/profiles";
import type { Olt } from "@/lib/types";

const FLASH: Record<string, string> = {
  registrado: "Avistamentos registrados (à mão: não valem como leitura da OLT).", invalido: "Linhas inválidas: use “PON SERIAL [fabricante]”, uma por linha.",
  permissao: "Seu papel não permite esta ação.", falha: "Não foi possível concluir. Tente novamente.",
};
const field = "min-h-touch rounded-btn border border-line bg-bg px-3";

export default async function Pendentes({ searchParams }: { searchParams: Promise<{ olt?: string; condicao?: string; de?: string; ok?: string; erro?: string }> }) {
  if (!(await featuresOn("onu_discovery"))) notFound();   // recurso desligado: a tela não existe
  const { olt: oltParam, condicao, de, ok, erro } = await searchParams;
  const offset = /^[0-9]{1,6}$/.test(de ?? "") ? Number(de) : 0;
  const cond = (FILTERS as readonly string[]).includes(condicao ?? "") ? condicao : undefined;
  const olts = await apiSafe<Olt[]>("/v1/olts?limit=200");
  const list = olts.data ?? [];
  const sel = list.find((o) => o.id === oltParam && UUID.test(o.id));
  const q = new URLSearchParams(); if (cond) q.set("condition", cond); if (offset) q.set("offset", String(offset));
  const queue = await apiSafe<PendingList>(sel ? `/v1/olts/${sel.id}/onus/unregistered${q.size ? `?${q}` : ""}` : `/v1/discovery/onus${q.size ? `?${q}` : ""}`);
  if (queue.status === 403) return <AppShell active="/rede" user="1"><ErrorState title="Sem permissão" hint="Seu papel não permite ver as ONUs aguardando autorização." /></AppShell>;
  const msg = ok ? FLASH[ok] : erro ? FLASH[erro] : null;
  const href = (o?: string, c?: string, d?: number) => `/rede/pendentes${o || c || d ? "?" : ""}${[o ? `olt=${o}` : "", c ? `condicao=${c}` : "", d ? `de=${d}` : ""].filter(Boolean).join("&")}`;
  const chip = (on: boolean) => `inline-flex min-h-touch items-center rounded-btn border px-3 text-sm ${on ? "border-accent bg-accent-soft font-semibold" : "border-line hover:bg-bg"}`;
  const items = queue.data?.items ?? [];
  return (
    <AppShell active="/rede" user="1">
      <PageHeader title="ONUs aguardando autorização" subtitle="Seriais avistados e ainda não registrados na OLT. Somente leitura: nada é autorizado aqui." helpSlug="rede/onus-pendentes">
        <Link href="/rede" className="inline-flex min-h-touch items-center rounded-btn px-3 text-sm text-accent hover:underline">← Voltar para Rede</Link>
      </PageHeader>
      {msg && <p role={erro ? "alert" : "status"} data-testid="pend-flash" className={`mb-4 rounded-btn border px-3 py-2 text-sm ${erro ? "border-danger text-danger" : "border-ok text-ok"}`}>{msg}</p>}
      <p data-testid="pend-aviso" className="mb-4 rounded-btn border border-line px-3 py-2 text-sm text-muted">A autorização de ONU <strong>não existe nesta versão</strong>: depende de homologação em laboratório e de aprovação. A lista é só evidência, com a origem de cada avistamento.</p>
      <div className="grid gap-4">
        <nav aria-label="Filtros" className="flex flex-wrap gap-2">
          <Link href={href(sel?.id)} className={chip(!cond)} data-testid="pend-filtro-todas">Todas</Link>
          {FILTERS.map((c) => <Link key={c} href={href(sel?.id, c)} className={chip(cond === c)} data-testid={`pend-filtro-${c}`}>{CONDITION_LABEL[c]}</Link>)}
          <form method="get" className="ml-auto flex items-center gap-2">
            {cond && <input type="hidden" name="condicao" value={cond} />}
            <label className="text-sm">OLT<select name="olt" defaultValue={sel?.id ?? ""} className={`${field} ml-2`}><option value="">Todas</option>{list.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}</select></label>
            <button type="submit" className="min-h-touch rounded-btn border border-line px-3 hover:bg-bg">Filtrar</button>
          </form>
        </nav>
        <section aria-label="Fila" data-testid="pend-fila" className="panel p-4">
          {queue.status !== 200 ? <ErrorState title="Falha ao carregar a fila" hint="Tente novamente em instantes." /> : items.length === 0 ? <EmptyState title="Nenhuma ONU aguardando" hint="A fila é preenchida pela leitura da OLT (após captura supervisionada) ou por avistamentos registrados à mão." /> : (
            <div className="overflow-x-auto"><table className="w-full text-sm">
              <caption className="sr-only">ONUs aguardando autorização</caption>
              <thead><tr className="text-left text-xs text-muted"><th scope="col" className="py-1 pr-3">Última vez vista</th><th scope="col" className="pr-3">OLT / PON</th><th scope="col" className="pr-3">Serial</th><th scope="col" className="pr-3">Fabricante provável</th><th scope="col" className="pr-3">Assinante / OS</th><th scope="col" className="pr-3">Condição</th><th scope="col">Ação</th></tr></thead>
              <tbody>{items.map((i) => (
                <tr key={i.id} data-testid="pend-linha" className="border-t border-line align-top">
                  <td className="py-2 pr-3"><span data-testid="volatile">{new Date(i.last_seen_at).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" })}</span><span className="block text-xs text-muted">visto {i.seen_count}×</span></td>
                  <td className="pr-3">{i.olt_name}<span className="block text-xs text-muted">PON {i.pon_path}</span></td>
                  <td className="pr-3 font-mono">{i.serial}</td>
                  <td className="pr-3">{i.vendor_hint ?? "—"}</td>
                  <td className="pr-3 text-xs text-muted">{ASSOC_LABEL[i.erp_association] ?? i.erp_association}</td>
                  <td className="pr-3"><span className={CONDITION_CLS[i.condition]}><span aria-hidden>{CONDITION_MARK[i.condition]} </span>{CONDITION_LABEL[i.condition]}</span>
                    {i.reasons.map((r) => <span key={r} className="block text-xs text-muted">{REASON_LABEL[r] ?? r}</span>)}
                    <span className="block text-xs text-muted">{SOURCE_LABEL[i.source] ?? i.source}{!i.authoritative && " · não vale como leitura da OLT"}</span></td>
                  <td className="text-xs text-muted">Autorização indisponível nesta versão</td>
                </tr>))}</tbody>
            </table></div>
          )}
          {queue.data && queue.data.total > 0 && <p data-testid="pend-contagem" className="mt-2 text-xs text-muted">Mostrando {queue.data.offset + 1}–{queue.data.offset + items.length} de {queue.data.total}.</p>}
          {queue.data?.scan_capped && <p className="mt-2 text-xs text-warn">Lista parcial: há mais avistamentos que o limite de leitura; o total pode estar incompleto.</p>}
          <div className="mt-2 flex gap-3 text-sm">
            {offset > 0 && <Link href={href(sel?.id, cond, Math.max(0, offset - (queue.data?.limit ?? 200)))} className="text-accent hover:underline" data-testid="pend-anterior">← Anteriores</Link>}
            {queue.data?.truncated && <Link href={href(sel?.id, cond, offset + (queue.data.limit))} className="text-accent hover:underline" data-testid="pend-proximas">Próximas →</Link>}
          </div>
        </section>
        {sel && (
          <details className="panel p-4" data-testid="pend-registrar">
            <summary className="cursor-pointer text-sm font-semibold uppercase tracking-wide text-muted">Registrar avistamentos à mão em {sel.name}</summary>
            <form method="post" action="/bff/descoberta/importar" className="mt-3 grid gap-3">
              <input type="hidden" name="olt" value={sel.id} />
              <label className="grid gap-1 text-sm">Uma ONU por linha: PON, serial e (opcional) fabricante
                <textarea name="linhas" required rows={4} placeholder={"0/1/3 ABCD12345678 huawei"} spellCheck={false} className="rounded-btn border border-line bg-bg p-3 font-mono text-xs" /></label>
              <p className="text-xs text-muted">Vale como registro de quem viu, nunca como leitura da OLT. O horário é o de agora.</p>
              <button type="submit" className="min-h-touch rounded-btn bg-accent px-4 font-semibold text-white">Registrar</button>
            </form>
          </details>
        )}
      </div>
    </AppShell>
  );
}
