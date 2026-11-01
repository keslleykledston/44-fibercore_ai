"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  lossText, msText, PING_ACTIVE, PING_BLOCKED_TEXT, PING_REASON_TEXT, PING_STATUS_TEXT, type PingCaps, type PingRun, readPingCaps, readPingRuns,
} from "@/lib/ping";

type Load = { kind: "loading" } | { kind: "error"; code: string } | { kind: "ready"; caps: PingCaps; runs: PingRun[] };
const LOAD_ERROR: Record<string, string> = {
  disabled: "O teste de ping está desligado para este provedor.", not_found: "Este aparelho não existe mais.", session: "Sua sessão expirou. Recarregue a página e entre de novo.",
  failed: "Não foi possível carregar o teste de ping agora.",
};
const when = (iso: string) => new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
const POLL_MS = 4000;
const UNCERTAIN_MS = 60_000;

/** Ping da ONT pela WAN de serviço (TR-143 IPPing, ADR-0039). Mede latência mínima/média/máxima e perda até um destino do provedor; NÃO mede jitter (o aparelho não informa tempo por pacote: mostramos a amplitude
 *  máx − mín) nem DNS (nenhum modelo de bancada expõe o teste). Nada inicia sozinho: cada teste é pedido por uma pessoa com permissão e aprovado por outra. */
export function PingTestSection({ cpeId }: { cpeId: string }) {
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [target, setTarget] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);
  const [lockUntil, setLockUntil] = useState(0);   // resposta perdida: o pedido pode ter sido gravado; trava por pouco tempo e deixa a leitura dizer
  const alive = useRef(true);
  const seq = useRef(0);
  const hasData = useRef(false);
  const [refreshFailed, setRefreshFailed] = useState(false);

  const fetchAll = useCallback(async (signal?: AbortSignal) => {
    const mine = ++seq.current;
    try {
      const r = await fetch(`/bff/cpes/${cpeId}/ping`, { cache: "no-store", signal });
      const j = (await r.json().catch(() => ({}))) as { caps?: unknown; runs?: unknown; error?: string };
      const caps = r.ok ? readPingCaps(j.caps) : null, runs = r.ok ? readPingRuns({ items: j.runs }) : null;
      if (!alive.current || mine !== seq.current) return;
      if (caps && runs) { hasData.current = true; setRefreshFailed(false); setLoad({ kind: "ready", caps, runs }); return; }
      const code = j.error && LOAD_ERROR[j.error] ? j.error : "failed";
      if (hasData.current && code === "failed") setRefreshFailed(true); else { setRefreshFailed(false); setLoad({ kind: "error", code }); }
    } catch (e) {
      if ((e as Error).name === "AbortError" || !alive.current || mine !== seq.current) return;
      if (hasData.current) setRefreshFailed(true); else setLoad({ kind: "error", code: "failed" });
    }
  }, [cpeId]);

  useEffect(() => { alive.current = true; const c = new AbortController(); void fetchAll(c.signal); return () => { alive.current = false; c.abort(); }; }, [fetchAll]);
  const active = load.kind === "ready" && load.runs.some((r) => PING_ACTIVE.has(r.status));
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => void fetchAll(), POLL_MS);
    return () => clearInterval(t);
  }, [active, fetchAll]);
  useEffect(() => {   // escolhe o primeiro destino pronto quando a lista chega
    if (load.kind === "ready" && !load.caps.targets.some((t) => t.id === target && t.ready)) setTarget(load.caps.targets.find((t) => t.ready)?.id ?? "");
  }, [load, target]);

  if (load.kind === "loading") return <p className="text-sm text-muted" data-testid="ping-loading">Carregando o teste de ping…</p>;
  if (load.kind === "error") {
    return (
      <div role="alert" className="grid gap-2 text-sm" data-testid="ping-error">
        <p className="text-danger">{LOAD_ERROR[load.code]}</p>
        {load.code === "session" && <a href="/login" className="min-h-touch w-fit rounded-btn border border-line px-3 py-2 text-accent">Entrar de novo</a>}
        {load.code === "failed" && <button type="button" onClick={() => { setLoad({ kind: "loading" }); void fetchAll(); }} className="min-h-touch w-fit rounded-btn border border-line px-3">Tentar novamente</button>}
      </div>
    );
  }
  const { caps, runs } = load;
  const history = runs.slice(0, 5);
  const last = runs[0];
  const locked = busy || active || Date.now() < lockUntil;

  const start = async () => {
    if (!target || locked) return;
    setBusy(true); setRefusal(null);
    try {
      const r = await fetch(`/bff/cpes/${cpeId}/ping/runs`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ key: crypto.randomUUID(), target_id: target }) });
      const j = (await r.json().catch(() => ({}))) as { error?: string; reason?: string };
      const definitive = [400, 401, 403, 404, 409, 413].includes(r.status);   // só estes garantem que NADA foi criado
      if (!r.ok && !definitive) { setLockUntil(Date.now() + UNCERTAIN_MS); setRefusal("Não foi possível confirmar o pedido. Aguarde a atualização antes de pedir de novo."); }
      else if (!r.ok) setRefusal(j.error === "blocked" && j.reason ? PING_BLOCKED_TEXT[j.reason] ?? "O pedido foi recusado." : j.error === "forbidden" ? PING_BLOCKED_TEXT.not_permitted! : "Não foi possível pedir o teste agora.");
      await fetchAll();
    } catch {
      setLockUntil(Date.now() + UNCERTAIN_MS);
      setRefusal("Não foi possível confirmar o pedido. Aguarde a atualização antes de pedir de novo.");
    } finally { setBusy(false); }
  };

  const blockedReason = !caps.offered ? (caps.reason ?? "operation_not_homologated") : null;
  const done = last && (last.status === "completed");
  return (
    <div className="grid gap-4" data-testid="ping-section">
      <p className="text-sm text-muted">Mede latência e perda da WAN de serviço da ONT até um destino do provedor ({caps.repetitions} envios, espera de {caps.timeout_ms / 1000} s por resposta). O teste gera tráfego no aparelho; nada inicia sozinho.</p>
      {blockedReason ? (
        <div className="grid gap-2 rounded-card border border-line p-3 text-sm" data-testid="ping-blocked" data-reason={blockedReason}>
          <p className="font-medium">Teste indisponível neste aparelho</p>
          <p className="text-muted">{PING_BLOCKED_TEXT[blockedReason] ?? "O teste não está liberado para este aparelho."}</p>
        </div>
      ) : !caps.ready ? (
        <div className="grid gap-2 rounded-card border border-line p-3 text-sm" data-testid="ping-not-ready">
          <p className="font-medium">Sem destino de ping pronto</p>
          <p className="text-muted">{caps.targets.length === 0 ? "Nenhum destino de ping foi cadastrado para este provedor." : "Nenhum destino está pronto para este aparelho."}</p>
        </div>
      ) : (
        <div className="grid gap-2">
          <div className="grid gap-1">
            <label htmlFor={`ping-target-${cpeId}`} className="text-sm font-medium">Destino</label>
            <select id={`ping-target-${cpeId}`} value={target} onChange={(e) => setTarget(e.target.value)} className="min-h-touch w-fit max-w-full rounded-btn border border-line bg-surface px-3 text-sm" data-testid="ping-target">
              {caps.targets.map((t) => <option key={t.id} value={t.id} disabled={!t.ready}>{t.label} · {t.target_kind === "CORE" ? "Core" : "Internet"}{t.ready ? "" : " (indisponível)"}</option>)}
            </select>
          </div>
          <button type="button" data-testid="ping-start" onClick={() => void start()} disabled={locked || !target}
            className="min-h-touch w-fit rounded-btn bg-accent px-4 text-sm font-medium text-[color:var(--on-accent)] disabled:opacity-50">Pedir teste de ping</button>
          <p className="text-xs text-muted">Pedido por quem tem permissão e aprovado por outra pessoa em Operações. Limite de {caps.per_hour} testes por hora neste aparelho.</p>
        </div>
      )}
      {refusal && <p role="alert" className="text-sm text-danger" data-testid="ping-refusal">{refusal}</p>}
      {refreshFailed && <p role="status" className="text-xs text-warn" data-testid="ping-refresh-failed">Não foi possível atualizar agora. O que aparece pode estar desatualizado; tentando de novo.</p>}
      {active && <div role="status" className="rounded-card border border-line p-3 text-sm" data-testid="ping-active">{runs.filter((r) => PING_ACTIVE.has(r.status)).map((r) => <p key={r.id}>{PING_STATUS_TEXT[r.status]}</p>)}</div>}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4" data-testid="ping-kpis">
        {[["Latência mínima", msText(done ? last.min_ms : null)], ["Latência média", msText(done ? last.avg_ms : null)], ["Latência máxima", msText(done ? last.max_ms : null)], ["Perda", lossText(done ? last.loss_pct : null)]].map(([t, v]) => (
          <div key={t} className="rounded-card border border-line p-3"><p className="text-xs text-muted">{t}</p><p className="text-xl font-semibold tabular-nums">{v}</p></div>
        ))}
      </div>
      <p className="text-xs text-muted" data-testid="ping-limits">
        {done && last.spread_ms !== null ? `Amplitude (máx − mín): ${msText(last.spread_ms)}. ` : ""}
        Jitter e DNS: não disponíveis nestes modelos (o aparelho informa só mínimo, média e máximo e não expõe o teste de DNS).
      </p>
      {history.length > 0 && (
        <details data-testid="ping-history" className="text-sm">
          <summary className="min-h-touch cursor-pointer py-2">Últimos testes ({history.length})</summary>
          <ul className="grid gap-2">
            {history.map((r) => (
              <li key={r.id} className="rounded-card border border-line p-2" data-testid="ping-history-row">
                <p className="font-medium">{PING_STATUS_TEXT[r.status] ?? "—"}{r.status === "completed" ? ` · perda ${lossText(r.loss_pct)} · média ${msText(r.avg_ms)}` : ""}</p>
                <p className="text-xs text-muted">{when(r.created_at)} · destino {r.target_id}{r.sent !== null ? ` · ${r.success}/${r.sent} respostas` : ""}</p>
                {r.reason && <p className="text-xs text-muted">{PING_REASON_TEXT[r.reason] ?? "Sem detalhe adicional."}</p>}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
