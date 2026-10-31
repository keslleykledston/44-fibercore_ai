"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ageText, CONFIDENCE_TEXT, GLOBAL_TEXT, INDICATOR_TEXT, INDICATOR_TITLE, INDICATORS, LOAD_ERROR, METRIC_TEXT, OBSERVATION_TEXT, readCaps, readRuns,
  REFUSAL_TEXT, SCOPE_TEXT, STATUS_TEXT, UNJUDGED_TEXT, valueText, type QCaps, type QRun,
} from "@/lib/quality";

type Load = { kind: "loading" } | { kind: "error"; code: string } | { kind: "ready"; caps: QCaps; runs: QRun[] };
const when = (iso: string) => new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
const TONE: Record<string, string> = { attention: "text-danger", ok: "text-ok", stale: "text-warn", unknown: "text-muted" };

/** Diagnóstico de qualidade da ONT (QoS-001, ADR-0039), no painel da ONU e na ONU 360°. Só LÊ o que o produto já tem (cache do ACS e OLT): não gera tráfego, não escreve no aparelho
 * e não inicia teste algum. Sem dado, diz "sem leitura"; nunca mostra zero nem "OK". Hipóteses são hipóteses, com a ressalva e a verificação recomendada. */
export function QualitySection({ cpeId }: { cpeId: string }) {
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);
  const [refreshFailed, setRefreshFailed] = useState(false);
  const alive = useRef(true);
  const seq = useRef(0);   // só a leitura MAIS RECENTE atualiza a tela
  const hasData = useRef(false);

  const fetchAll = useCallback(async (signal?: AbortSignal) => {
    const mine = ++seq.current;
    const fail = (code: string) => {
      if (code === "session" || code === "disabled" || code === "not_found") { setRefreshFailed(false); setLoad({ kind: "error", code }); }
      else if (hasData.current) setRefreshFailed(true);
      else setLoad({ kind: "error", code });
    };
    try {
      const r = await fetch(`/bff/cpes/${cpeId}/quality`, { cache: "no-store", signal });
      const j = (await r.json().catch(() => ({}))) as { caps?: unknown; runs?: unknown; error?: string };
      const caps = r.ok ? readCaps(j.caps) : null, runs = r.ok ? readRuns({ runs: j.runs }) : null;
      if (!alive.current || mine !== seq.current) return;
      if (caps && runs) { hasData.current = true; setRefreshFailed(false); setLoad({ kind: "ready", caps, runs }); }
      else fail(j.error && LOAD_ERROR[j.error] ? j.error : "failed");
    } catch (e) { if ((e as Error).name !== "AbortError" && alive.current && mine === seq.current) fail("failed"); }
  }, [cpeId]);

  useEffect(() => { alive.current = true; const c = new AbortController(); void fetchAll(c.signal); return () => { alive.current = false; c.abort(); }; }, [fetchAll]);

  if (load.kind === "loading") return <p className="text-sm text-muted" data-testid="quality-loading">Carregando o diagnóstico de qualidade…</p>;
  if (load.kind === "error") {
    return (
      <div role="alert" className="grid gap-2 text-sm" data-testid="quality-error">
        <p className="text-danger">{LOAD_ERROR[load.code]}</p>
        {load.code === "session" && <a href="/login" className="min-h-touch w-fit rounded-btn border border-line px-3 py-2 text-accent">Entrar de novo</a>}
        {load.code === "failed" && <button type="button" onClick={() => { setLoad({ kind: "loading" }); void fetchAll(); }} className="min-h-touch w-fit rounded-btn border border-line px-3">Tentar novamente</button>}
      </div>
    );
  }
  const { caps, runs } = load;
  const run = runs[0];

  const start = async () => {
    if (busy) return;
    setBusy(true); setRefusal(null);
    try {
      const r = await fetch(`/bff/cpes/${cpeId}/quality/runs`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ key: crypto.randomUUID() }) });
      const j = (await r.json().catch(() => ({}))) as { error?: string };
      if (!r.ok) setRefusal(REFUSAL_TEXT[j.error ?? ""] ?? "Não foi possível fazer a leitura agora.");
      await fetchAll();
    } catch { setRefusal("Não foi possível fazer a leitura agora."); }
    finally { setBusy(false); }
  };

  const byGroup = run ? Object.entries(run.metrics.reduce<Record<string, QRun["metrics"]>>((a, m) => { (a[m.group] ??= []).push(m); return a; }, {})) : [];
  return (
    <div className="grid gap-4" data-testid="quality-section">
      <p className="text-sm text-muted">Reúne o que já se sabe do aparelho e da OLT. Não gera tráfego, não escreve no aparelho e não inicia nenhum teste. Sem leitura não significa defeito.</p>
      <div className="flex flex-wrap items-center gap-3">
        <button type="button" data-testid="quality-run" onClick={() => void start()} disabled={busy || !caps.modes.quick.offered}
          className="min-h-touch rounded-btn bg-accent px-4 text-sm font-medium text-[color:var(--on-accent)] disabled:opacity-50">
          {busy ? "Lendo…" : "Verificar agora"}
        </button>
        {!caps.modes.quick.offered && <p className="text-xs text-muted" data-testid="quality-not-offered">{REFUSAL_TEXT.forbidden}</p>}
      </div>
      {refusal && <p role="alert" className="text-sm text-danger" data-testid="quality-refusal">{refusal}</p>}
      {refreshFailed && <p role="status" className="text-xs text-warn" data-testid="quality-refresh-failed">Não foi possível atualizar agora. O que aparece pode estar desatualizado.</p>}
      {!run ? (
        <p className="rounded-card border border-line p-3 text-sm text-muted" data-testid="quality-empty">Nenhuma leitura feita ainda para este aparelho.</p>
      ) : (
        <>
          <div className="grid gap-1 rounded-card border border-line p-3" data-testid="quality-global" data-state={run.summary.state}>
            <p className={`font-medium ${run.summary.state === "attention" ? "text-danger" : ""}`}>{GLOBAL_TEXT[run.summary.state]}</p>
            <p className="text-xs text-muted">Leitura de {when(run.created_at)}. Dados mais antigos que o prazo de cada grupo aparecem como "leitura antiga".</p>
            {run.summary.note && <p className="text-xs text-muted">{run.summary.note[0]!.toUpperCase() + run.summary.note.slice(1)}.</p>}
          </div>
          <div className="grid grid-cols-2 gap-3" data-testid="quality-indicators">
            {INDICATORS.map((k) => {
              const s = run.summary.indicators[k].state;
              const unjudged = k === "optical" && s === "ok" && !run.metrics.some((m) => m.id === "optical.rx_dbm" && m.status === "valid" && m.judged === true);
              return (
                <div key={k} className="rounded-card border border-line p-3" data-testid={`quality-ind-${k}`} data-state={unjudged ? "unjudged" : s}>
                  <p className="text-xs text-muted">{INDICATOR_TITLE[k]}</p>
                  <p className={`text-sm font-semibold ${unjudged ? "text-muted" : TONE[s]}`}>{unjudged ? UNJUDGED_TEXT : INDICATOR_TEXT[s]}</p>
                </div>
              );
            })}
          </div>
          {run.summary.observations.length > 0 && (
            <ul className="grid gap-1 text-sm" data-testid="quality-observations">
              {run.summary.observations.map((o, i) => <li key={`${o.code}${i}`} className="rounded-card border border-line p-2">{OBSERVATION_TEXT[o.code] ?? "Há um indício a verificar."}</li>)}
            </ul>
          )}
          {run.hypotheses.length > 0 && (
            <div className="grid gap-2" data-testid="quality-hypotheses">
              <p className="text-sm font-medium">Hipóteses (não são diagnóstico)</p>
              {run.hypotheses.map((h) => (
                <div key={h.code} className="rounded-card border border-line p-3 text-sm" data-testid="quality-hypothesis">
                  <p>{h.label} <span className="text-xs text-muted">({CONFIDENCE_TEXT[h.confidence] ?? "confiança baixa"})</span></p>
                  <p className="text-xs text-muted">Verificar: {h.recommended_check}</p>
                  {h.caveats.map((c, i) => <p key={i} className="text-xs text-muted">Ressalva: {c}</p>)}
                </div>
              ))}
            </div>
          )}
          <details data-testid="quality-details" className="text-sm">
            <summary className="min-h-touch cursor-pointer py-2">Ver detalhes por camada</summary>
            <div className="grid gap-3">
              {byGroup.map(([g, ms]) => (
                <div key={g} className="grid gap-1">
                  <p className="text-xs font-medium uppercase text-muted">{g}</p>
                  {ms.map((m, i) => (
                    <div key={`${m.id}${m.instance ?? ""}${i}`} className="rounded-card border border-line p-2" data-testid="quality-metric" data-status={m.status}>
                      <p className="font-medium">{METRIC_TEXT[m.id] ?? m.id}: {valueText(m)} <span className="text-xs font-normal text-muted">· {STATUS_TEXT[m.status]}{m.freshness_s !== null && (m.status === "valid" || m.status === "stale") ? ` · ${ageText(m.freshness_s)}` : ""}</span></p>
                      <p className="text-xs text-muted">{SCOPE_TEXT[m.scope] ?? m.scope}{m.instance ? ` · ${m.instance}` : ""}</p>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          </details>
        </>
      )}
      <Link href="/ajuda/rede/qualidade-do-servico" className="text-xs text-accent underline underline-offset-2">Como ler o diagnóstico de qualidade</Link>
    </div>
  );
}
