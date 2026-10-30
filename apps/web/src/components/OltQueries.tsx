"use client";

import { useEffect, useRef, useState } from "react";
import { EntityDetailDrawer } from "@/components/EntityDetailDrawer";
import { QUERY_ERROR, QUERY_FAILED, QUERY_UNAVAILABLE, readBoard, readVersion, uptimeText, type OltQueryItem } from "@/lib/olt-queries";

type Phase = { kind: "idle" } | { kind: "waiting"; jobId: string; since: number; queryId: string } | { kind: "done"; queryId: string; data: unknown } | { kind: "failed"; reason: string };
const POLL_MS = 10_000;
const GIVE_UP_MS = 25 * 60_000; // o pedido vive 22 min na nuvem; depois disso a tela para de perguntar

function Result({ queryId, data }: { queryId: string; data: unknown }) {
  if (queryId === "olt.version") {
    const v = readVersion(data);
    if (!v) return <p>O resultado não tinha o formato esperado e não foi mostrado.</p>;
    return (
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1" data-testid="olt-query-result">
        <dt className="text-muted">Produto</dt><dd className="font-mono">{v.product}</dd>
        <dt className="text-muted">Versão</dt><dd className="font-mono">{v.version}</dd>
        <dt className="text-muted">Patch</dt><dd className="font-mono">{v.patch}</dd>
        <dt className="text-muted">Ligada há</dt><dd>{uptimeText(v.uptime_seconds)}</dd>
      </dl>
    );
  }
  if (queryId === "olt.board") {
    const b = readBoard(data);
    if (!b) return <p>O resultado não tinha o formato esperado e não foi mostrado.</p>;
    return (
      <div data-testid="olt-query-result" className="grid gap-2">
        <table className="w-full text-left">
          <caption className="sr-only">Placas da OLT</caption>
          <thead><tr className="text-muted"><th scope="col" className="py-1 pr-3">Slot</th><th scope="col" className="pr-3">Placa</th><th scope="col">Estado</th></tr></thead>
          <tbody>{b.boards.map((x) => <tr key={x.slot} className="border-t border-line"><td className="py-1 pr-3">{x.slot}</td><td className="pr-3 font-mono">{x.name}</td><td>{x.status}</td></tr>)}</tbody>
        </table>
        {b.empty_slots.length > 0 && <p className="text-muted">Slots vazios: {b.empty_slots.join(", ")}</p>}
      </div>
    );
  }
  return <p>Esta consulta não tem exibição.</p>;
}

/** Consultas somente leitura de uma OLT. O pedido entra numa fila e roda na próxima janela da coleta (até ~18 min): a tela mostra o estado, não promete tempo real. */
export function OltQueries({ oltId, oltName }: { oltId: string; oltName: string }) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<OltQueryItem[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [chosen, setChosen] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const key = useRef(`ui-${crypto.randomUUID()}`);
  const trigger = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open || items !== null) return;
    let live = true;
    fetch(`/bff/olts/${oltId}/queries`, { cache: "no-store" }).then(async (r) => {
      const j = (await r.json().catch(() => ({}))) as { items?: OltQueryItem[]; error?: string };
      if (!live) return;
      if (r.ok && j.items) { setItems(j.items); setChosen(j.items.find((i) => i.offered && i.fields.length === 0)?.id ?? ""); }
      else setLoadError(QUERY_ERROR[j.error ?? "failed"] ?? QUERY_ERROR.failed);
    }).catch(() => live && setLoadError(QUERY_ERROR.failed));
    return () => { live = false; };
  }, [open, items, oltId]);

  useEffect(() => {
    if (phase.kind !== "waiting" || !open) return;   // sem gaveta aberta não há polling; reabrir retoma o MESMO pedido
    const { jobId, since, queryId } = phase;
    const t = setInterval(async () => {
      if (Date.now() - since > GIVE_UP_MS) { setPhase({ kind: "failed", reason: "expired" }); return; }
      const r = await fetch(`/bff/jobs/${jobId}`, { cache: "no-store" }).catch(() => null);
      const j = (await r?.json().catch(() => null)) as { status?: string; detail?: string | null; data?: unknown } | null;
      if (!r?.ok || !j) return;
      if (j.status === "SUCCEEDED") { setPhase({ kind: "done", queryId, data: j.data ?? null }); key.current = `ui-${crypto.randomUUID()}`; }
      else if (["FAILED", "EXPIRED", "CANCELLED", "UNKNOWN"].includes(j.status ?? "")) { setPhase({ kind: "failed", reason: j.status === "UNKNOWN" ? "restart_after_claim" : j.status === "EXPIRED" ? "expired" : (j.detail ?? "") }); key.current = `ui-${crypto.randomUUID()}`; }
    }, POLL_MS);
    return () => clearInterval(t);
  }, [phase, open]);

  async function ask(e: React.FormEvent) {
    e.preventDefault();
    if (!chosen) return;
    const queryId = chosen, idem = `${key.current}-${queryId}`;   // consulta e chave fixadas no envio: trocar a seleção depois não muda o que foi pedido
    setBusy(true); setError(null);
    try {
      const res = await fetch(`/bff/olts/${oltId}/queries/${queryId}`, { method: "POST", headers: { "content-type": "application/json" }, cache: "no-store", body: JSON.stringify({ key: idem }) });
      const j = (await res.json().catch(() => ({}))) as { error?: string; job_id?: string | null };
      if (res.ok && j.job_id) { setPhase({ kind: "waiting", jobId: j.job_id, since: Date.now(), queryId }); return; }
      setError(QUERY_ERROR[j.error ?? "failed"] ?? QUERY_ERROR.failed);
    } catch { setError(QUERY_ERROR.failed); } finally { setBusy(false); }
  }

  const close = () => { setOpen(false); setError(null); trigger.current?.focus(); };
  const offered = (items ?? []).filter((i) => i.offered && i.fields.length === 0);
  const shown = phase.kind === "waiting" || phase.kind === "done" ? phase.queryId : chosen;
  const title = (items ?? []).find((i) => i.id === shown)?.title;
  return (
    <>
      <button ref={trigger} type="button" onClick={() => setOpen(true)} aria-haspopup="dialog" data-testid="olt-queries-open" className="mt-2 min-h-touch rounded-btn border border-line px-3 text-sm hover:bg-bg">Consultar a OLT…</button>
      <EntityDetailDrawer open={open} onClose={close} title={`Consultar ${oltName}`}>
        <div className="grid gap-4 text-sm" data-testid="olt-queries">
          <div role="note" className="rounded-btn border border-line bg-bg p-3">
            <p className="font-medium">O que acontece</p>
            <ul className="mt-1 list-disc pl-5 text-muted">
              <li>É uma consulta <strong>somente leitura</strong>: nada é alterado na OLT.</li>
              <li>Ela roda na <strong>próxima coleta</strong> da OLT, na mesma sessão, para não abrir logins a mais. Pode levar até uns 18 minutos.</li>
              <li>Só o resultado já resumido chega aqui; a saída bruta do equipamento nunca sai do Edge.</li>
            </ul>
          </div>
          {loadError && <p role="alert" className="text-danger">{loadError}</p>}
          {items === null && !loadError && <p className="text-muted">Carregando as consultas…</p>}
          {items !== null && phase.kind === "idle" && (
            <form onSubmit={ask} className="grid gap-3" data-testid="olt-queries-form">
              {offered.length === 0 ? <p data-testid="olt-queries-none" className="text-muted">Nenhuma consulta está disponível agora para você nesta OLT.</p> : (
                <fieldset disabled={busy} className="grid gap-2"><legend className="mb-1 font-medium">Consulta</legend>
                  {offered.map((i) => (
                    <label key={i.id} className="flex min-h-touch items-center gap-2">
                      <input type="radio" name="query" value={i.id} checked={chosen === i.id} onChange={() => setChosen(i.id)} /> {i.title}
                    </label>
                  ))}
                </fieldset>
              )}
              <ul className="text-xs text-muted">
                {(items ?? []).filter((i) => !i.offered && i.fields.length === 0).slice(0, 4).map((i) => <li key={i.id}>{i.title}: {QUERY_UNAVAILABLE[i.reason ?? ""] ?? "indisponível."}</li>)}
              </ul>
              {error && <p role="alert" data-testid="olt-queries-error" className="text-danger">{error}</p>}
              {offered.length > 0 && <button type="submit" disabled={busy || !chosen} className="min-h-touch rounded-btn bg-accent px-4 font-medium text-[color:var(--on-accent)] disabled:opacity-60">{busy ? "Pedindo…" : "Pedir consulta"}</button>}
            </form>
          )}
          {phase.kind === "waiting" && (
            <div role="status" data-testid="olt-queries-waiting" className="grid gap-2">
              <p><strong>Pedido enviado: {title}.</strong> Aguardando a próxima coleta da OLT. Esta tela confere a cada 10 s; você pode fechá-la e pedir de novo depois.</p>
            </div>
          )}
          {phase.kind === "done" && (
            <div role="status" className="grid gap-3" data-testid="olt-queries-done">
              <p><strong>{title}</strong></p>
              <Result queryId={phase.queryId} data={phase.data} />
              <button type="button" onClick={() => setPhase({ kind: "idle" })} className="min-h-touch rounded-btn border border-line px-3">Nova consulta</button>
            </div>
          )}
          {phase.kind === "failed" && (
            <div role="alert" className="grid gap-3" data-testid="olt-queries-failed">
              <p><strong>A consulta não devolveu resultado.</strong> {QUERY_FAILED[phase.reason] ?? "O Edge informou uma falha."}</p>
              <button type="button" onClick={() => setPhase({ kind: "idle" })} className="min-h-touch rounded-btn border border-line px-3">Tentar de novo</button>
            </div>
          )}
        </div>
      </EntityDetailDrawer>
    </>
  );
}
