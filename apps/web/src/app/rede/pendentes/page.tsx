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
  semleitura: "O Edge ainda não leu a lista de ONUs detectadas desta OLT. Peça a consulta “ONTs detectadas e não confirmadas” em Consultas da OLT e tente de novo.",
  leituraantiga: "A última leitura é antiga demais (mais de 1 hora). Peça a consulta de novo e tente outra vez.",
  leituraruim: "A última leitura não pôde ser usada (origem ou formato inesperados). Nada foi registrado.",
};
const field = "min-h-touch rounded-btn border border-line bg-bg px-3";

export default async function Pendentes({ searchParams }: { searchParams: Promise<{ olt?: string; condicao?: string; de?: string; ok?: string; erro?: string; n?: string; u?: string; s?: string }> }) {
  if (!(await featuresOn("onu_discovery"))) notFound();   // recurso desligado: a tela não existe
  const { olt: oltParam, condicao, de, ok, erro, n, u, s: same } = await searchParams;
  const offset = /^[0-9]{1,6}$/.test(de ?? "") ? Number(de) : 0;
  const cond = (FILTERS as readonly string[]).includes(condicao ?? "") ? condicao : undefined;
  const olts = await apiSafe<Olt[]>("/v1/olts?limit=200");
  const list = olts.data ?? [];
  const sel = list.find((o) => o.id === oltParam && UUID.test(o.id));
  const q = new URLSearchParams(); if (cond) q.set("condition", cond); if (offset) q.set("offset", String(offset));
  const queue = await apiSafe<PendingList>(sel ? `/v1/olts/${sel.id}/onus/unregistered${q.size ? `?${q}` : ""}` : `/v1/discovery/onus${q.size ? `?${q}` : ""}`);
  if (queue.status === 403) return <AppShell active="/rede" user="1"><ErrorState title="Sem permissão" hint="Seu papel não permite ver as ONUs aguardando autorização." /></AppShell>;
  const cnt = (v?: string) => (/^\d{1,3}$/.test(v ?? "") ? Number(v) : 0);
  const msg = ok === "sincronizado" ? `Lista lida do Edge: ${cnt(n)} nova(s), ${cnt(u)} atualizada(s), ${cnt(same)} sem mudança. Vale como leitura da OLT; nada foi autorizado.` : ok ? FLASH[ok] : erro ? FLASH[erro] : null;
  const href = (o?: string, c?: string, d?: number) => `/rede/pendentes${o || c || d ? "?" : ""}${[o ? `olt=${o}` : "", c ? `condicao=${c}` : "", d ? `de=${d}` : ""].filter(Boolean).join("&")}`;
  const chip = (on: boolean) => `inline-flex min-h-touch items-center rounded-btn border px-3 text-sm ${on ? "border-accent bg-accent-soft font-semibold" : "border-line hover:bg-bg"}`;
  const items = queue.data?.items ?? [];
  // Uma fila vazia só quer dizer "nada pendente" se houver uma leitura recente do Edge: o estado dessa leitura vem junto da fila (a idade é a da PERGUNTA)
  const read = sel ? await apiSafe<{ asked_at: string; asked_age_seconds?: number; data?: { entries?: unknown[] }; source?: string }>(`/v1/olts/${sel.id}/queries/olt.autofind/latest`) : null;
  // A idade da PERGUNTA vem do servidor (`asked_age_seconds`, relógio da API): o navegador e o servidor web nunca decidem o frescor, e o limite é o do sync (1 h, inclusive)
  const askedAge = read?.status === 200 && read.data && typeof read.data.asked_age_seconds === "number" && Number.isFinite(read.data.asked_age_seconds) ? read.data.asked_age_seconds : null;
  const inFuture = askedAge !== null && askedAge < -300;   // carimbada no futuro além da tolerância da API (5 min): leitura inválida, nunca "recente"
  const ageMin = askedAge !== null && !inFuture ? Math.max(0, Math.floor(askedAge / 60)) : null;
  const readFresh = askedAge !== null && !inFuture && askedAge <= 3600 && read?.data?.source === "job";
  const nEntries = Array.isArray(read?.data?.data?.entries) ? read!.data!.data!.entries!.length : null;
  const readLine = !sel ? null : inFuture ? "A última leitura do Edge está carimbada no futuro e não pode ser usada: uma fila vazia não prova que não há ONUs aguardando."
    : read?.status === 200 && ageMin !== null ? (readFresh ? `Última leitura do Edge há ${ageMin} min: ${nEntries ?? "?"} ONU(s) detectada(s) na OLT.` : `A última leitura do Edge é antiga (há ${ageMin >= 120 ? `${Math.floor(ageMin / 60)} h` : `${ageMin} min`}): não dá para afirmar o que está aguardando agora.`)
    : read?.status === 404 ? "O Edge ainda não leu a lista de ONUs detectadas desta OLT: uma fila vazia não prova que não há ONUs aguardando."
    : "O estado da leitura do Edge não está disponível para o seu papel ou a consulta está desligada: uma fila vazia não prova que não há ONUs aguardando.";
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
          {queue.status !== 200 ? <ErrorState title="Falha ao carregar a fila" hint="Tente novamente em instantes." /> : items.length === 0 ? <EmptyState title={cond ? "Nenhuma ONU neste filtro" : "Nenhuma ONU na fila"} hint={cond ? "Nenhuma linha corresponde ao filtro escolhido; escolha “Todas” para ver o que a fila tem." : sel && readFresh && nEntries === 0 ? "A leitura recente do Edge não listou nenhuma ONU detectada nesta OLT." : sel && readFresh && (nEntries ?? 0) > 0 ? "A leitura recente listou ONUs, mas elas ainda não estão na fila: use “Atualizar a partir da última leitura do Edge”." : "A fila é preenchida pela leitura da OLT ou por avistamentos registrados à mão. Sem leitura recente do Edge, isto não prova que não há ONUs aguardando."} /> : (
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
          <div className="mt-2 flex gap-3 text-sm">
            {offset > 0 && <Link href={href(sel?.id, cond, Math.max(0, offset - (queue.data?.limit ?? 200)))} className="text-accent hover:underline" data-testid="pend-anterior">← Anteriores</Link>}
            {queue.data?.truncated && <Link href={href(sel?.id, cond, offset + (queue.data.limit))} className="text-accent hover:underline" data-testid="pend-proximas">Próximas →</Link>}
          </div>
        </section>
        {sel && (
          <form method="post" action="/bff/descoberta/sincronizar" className="panel flex flex-wrap items-center gap-3 p-4" data-testid="pend-sincronizar-form">
            <input type="hidden" name="olt" value={sel.id} />
            <button type="submit" data-testid="pend-sincronizar" className="min-h-touch rounded-btn border border-line px-4 text-sm hover:bg-bg">Atualizar a partir da última leitura do Edge</button>
            <span className="text-xs text-muted">Usa a lista de ONUs detectadas que o Edge já leu (até 1 hora); não pergunta nada à OLT e não autoriza nada.</span>
            {readLine && <p data-testid="pend-leitura" className={`w-full text-sm ${readFresh ? "text-muted" : "text-warn"}`}>{readLine}</p>}
          </form>
        )}
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
