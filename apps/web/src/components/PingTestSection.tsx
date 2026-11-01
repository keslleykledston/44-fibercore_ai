"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  lossText, msText, PING_ACTIVE, PING_BLOCKED_TEXT, PING_REASON_TEXT, PING_STATUS_TEXT, type PingCaps, type PingRun, readPingCaps, readPingRuns,
} from "@/lib/ping";

type Load = { kind: "loading" } | { kind: "error"; code: string } | { kind: "ready"; caps: PingCaps; runs: PingRun[] };
const LOAD_ERROR: Record<string, string> = {
  disabled: "O teste de ping está desligado para este provedor.", not_found: "Este aparelho não existe mais.", session: "Sua sessão expirou. Recarregue a página e entre de novo.",
  forbidden: "Seu papel não permite ver o teste de ping.", failed: "Não foi possível carregar o teste de ping agora.",
};
const when = (iso: string) => new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
const POLL_MS = 4000;
const PENDING_MS = 20 * 60_000;   // a vida do pedido na API é de 15 minutos
const UNCERTAIN_MS = 60_000;

// Marcador de pedido em curso, por aparelho, que sobrevive a fechar o painel, trocar de aba e recarregar (sessão do navegador): remontar a seção não pode reabrir o botão sobre um pedido ainda não
// esclarecido, e cada clique leva uma chave de idempotência nova, então só a trava impede um segundo tráfego.
// `runId` = a API respondeu sucesso e disse QUAL execução criou: só uma leitura que mostre ESSA execução destrava (a de outra pessoa não prova nada), nunca o relógio. Sem `runId` (resposta perdida ou sem
// o id): destrava só por uma leitura bem-sucedida FEITA DEPOIS do prazo.
type Pending = { runId: string | null; until: number };
const memo = new Map<string, Pending | null>();
const KEY = (cpe: string) => `fc-ping-pending:${cpe}`;
function readPending(cpe: string): Pending | null {
  if (memo.has(cpe)) return memo.get(cpe) ?? null;
  try {
    const raw = window.sessionStorage.getItem(KEY(cpe));
    const o = raw ? (JSON.parse(raw) as Pending) : null;
    const ok = !!o && (o.runId === null || typeof o.runId === "string") && typeof o.until === "number";
    memo.set(cpe, ok ? o : null);
  } catch { memo.set(cpe, null); }
  return memo.get(cpe) ?? null;
}
function writePending(cpe: string, p: Pending | null) {
  memo.set(cpe, p);
  try { if (p) window.sessionStorage.setItem(KEY(cpe), JSON.stringify(p)); else window.sessionStorage.removeItem(KEY(cpe)); } catch { /* sem armazenamento: vale só nesta página */ }
}

/** Ping da ONT pela WAN de serviço (TR-143 IPPing, ADR-0039). Mede latência mínima/média/máxima e perda até um destino do provedor; NÃO mede jitter (o aparelho não informa tempo por pacote: mostramos a amplitude
 *  máx − mín) nem DNS (nenhum modelo de bancada expõe o teste). Nada inicia sozinho: cada teste é pedido por uma pessoa com permissão e aprovado por outra. */
export function PingTestSection({ cpeId }: { cpeId: string }) {
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [target, setTarget] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);
  const [pending, setPendingState] = useState<Pending | null>(() => (typeof window === "undefined" ? null : readPending(cpeId)));
  const setPending = useCallback((next: Pending | null | ((p: Pending | null) => Pending | null)) => {
    setPendingState((prev) => { const v = typeof next === "function" ? next(prev) : next; writePending(cpeId, v); return v; });
  }, [cpeId]);
  const alive = useRef(true);
  const seq = useRef(0);
  const hasData = useRef(false);
  const [refreshFailed, setRefreshFailed] = useState(false);

  const fetchAll = useCallback(async (signal?: AbortSignal) => {
    const mine = ++seq.current;
    const startedAt = Date.now();
    try {
      const r = await fetch(`/bff/cpes/${cpeId}/ping`, { cache: "no-store", signal });
      const j = (await r.json().catch(() => ({}))) as { caps?: unknown; runs?: unknown; error?: string };
      const caps = r.ok ? readPingCaps(j.caps) : null, runs = r.ok ? readPingRuns({ items: j.runs }) : null;
      if (!alive.current || mine !== seq.current) return;
      if (caps && runs) {
        hasData.current = true; setRefreshFailed(false); setLoad({ kind: "ready", caps, runs });
        setPending((p) => (p && (p.runId ? runs.some((x) => x.id === p.runId) : startedAt > p.until) ? null : p));
        return;
      }
      const code = j.error && LOAD_ERROR[j.error] ? j.error : "failed";
      if (hasData.current && code === "failed") setRefreshFailed(true); else { setRefreshFailed(false); setLoad({ kind: "error", code }); }
    } catch (e) {
      if ((e as Error).name === "AbortError" || !alive.current || mine !== seq.current) return;
      if (hasData.current) setRefreshFailed(true); else setLoad({ kind: "error", code: "failed" });
    }
  }, [cpeId, setPending]);

  useEffect(() => { alive.current = true; const c = new AbortController(); void fetchAll(c.signal); return () => { alive.current = false; c.abort(); }; }, [fetchAll]);
  const active = load.kind === "ready" && load.runs.some((r) => PING_ACTIVE.has(r.status));
  const following = load.kind === "ready" && (active || pending !== null);
  useEffect(() => {   // enquanto há teste em andamento (ou um pedido ainda não confirmado pela leitura), acompanha; parado, não consulta
    if (!following) return;
    const t = setInterval(() => void fetchAll(), POLL_MS);
    return () => clearInterval(t);
  }, [following, fetchAll]);
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
  const locked = busy || active || pending !== null;

  const start = async () => {
    if (!target || locked) return;
    setBusy(true); setRefusal(null);
    try {
      const r = await fetch(`/bff/cpes/${cpeId}/ping/runs`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ key: crypto.randomUUID(), target_id: target }) });
      const j = (await r.json().catch(() => ({}))) as { error?: string; reason?: string; run_id?: unknown };
      const definitive = [400, 401, 403, 404, 409, 413].includes(r.status);   // só estes garantem que NADA foi criado
      if (r.ok) setPending({ runId: typeof j.run_id === "string" ? j.run_id : null, until: Date.now() + (typeof j.run_id === "string" ? PENDING_MS : UNCERTAIN_MS) });   // aceito: lembrado até uma leitura mostrar ESTA execução
      else if (!definitive) { setPending({ runId: null, until: Date.now() + UNCERTAIN_MS }); setRefusal("Não foi possível confirmar o pedido. Aguarde a atualização antes de pedir de novo."); }
      else setRefusal(j.error === "blocked" && j.reason ? PING_BLOCKED_TEXT[j.reason] ?? "O pedido foi recusado." : j.error === "forbidden" ? PING_BLOCKED_TEXT.not_permitted! : "Não foi possível pedir o teste agora.");
      await fetchAll();
    } catch {   // o pedido pode ter chegado: não se sabe. Trava até uma leitura mostrar ou o prazo passar
      setPending({ runId: null, until: Date.now() + UNCERTAIN_MS });
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
      {pending && !active && (
        <div role="status" className="grid gap-2 rounded-card border border-line p-3 text-sm" data-testid="ping-pending">
          <p>{pending.runId && Date.now() > pending.until
            ? "O pedido foi aceito, mas a leitura ainda não mostra a execução. Não peça de novo: use Atualizar. Se continuar assim, chame quem administra o Edge."
            : "Pedido enviado. Aguardando a confirmação da leitura; o botão fica travado até lá."}</p>
          <button type="button" onClick={() => void fetchAll()} data-testid="ping-pending-refresh" className="min-h-touch w-fit rounded-btn border border-line px-3">Atualizar agora</button>
        </div>
      )}
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
