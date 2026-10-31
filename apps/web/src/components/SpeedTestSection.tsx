"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ACTIVE, BLOCKED_TEXT, DIRECTION_TEXT, mbpsText, PROFILE_TEXT, qualityText, REASON_TEXT, STATUS_TEXT,
  type SpeedCaps, type SpeedDirection, type SpeedRun, readCaps, readRuns,
} from "@/lib/speed";

type Load = { kind: "loading" } | { kind: "error"; code: string } | { kind: "ready"; caps: SpeedCaps; runs: SpeedRun[] };
const LOAD_ERROR: Record<string, string> = {
  disabled: "O teste de banda está desligado para este provedor.", not_found: "Este aparelho não existe mais.", session: "Sua sessão expirou. Recarregue a página e entre de novo.",
  failed: "Não foi possível carregar o teste de banda agora.",
};
const when = (iso: string) => new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
const POLL_MS = 4000;
const PENDING_MS = 20 * 60_000;   // a vida do pedido na API é de 15 minutos
const UNCERTAIN_MS = 60_000;

function Kpi({ title, run }: { title: string; run: SpeedRun | undefined }) {
  const ok = run && (run.status === "completed" || run.status === "partial");
  return (
    <div className="rounded-card border border-line p-3" data-testid={`speed-kpi-${title === "Download" ? "download" : "upload"}`}>
      <p className="text-xs text-muted">{title}</p>
      <p className="text-xl font-semibold">{ok ? mbpsText(run.mbps) : "—"}</p>
      <p className="text-xs text-muted">{run ? (ok ? qualityText(run) : STATUS_TEXT[run.status] ?? "—") : "Sem teste ainda"}</p>
    </div>
  );
}

/** Teste de banda da ONT (TR-143, ADR-0038), no painel da ONU e na ONU 360°. Mede a WAN da ONT; não é Wi-Fi nem LAN. Nada inicia sozinho: cada sentido é pedido por uma pessoa com permissão, e hoje só o aparelho de bancada (com autorização prévia) pode executar. */
export function SpeedTestSection({ cpeId }: { cpeId: string }) {
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [kind, setKind] = useState<"CORE" | "INTERNET">("CORE");
  const [profile, setProfile] = useState("10mb");
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);
  // Um pedido ACEITO pela API é lembrado à parte do último retrato das execuções: se a leitura seguinte falha ou chega velha, a tela continua dizendo que há um pedido em curso
  // e os botões continuam travados (senão um novo clique geraria outro tráfego). Sai quando uma leitura mostra uma execução nova, ou depois do prazo de vida do pedido.
  // `certain` = a resposta da API foi sucesso (a execução EXISTE no servidor, que só responde depois de gravar): só uma leitura que a mostre destrava, nunca o relógio. `certain: false` = a
  // resposta se perdeu: pode ter chegado ou não; destrava só por uma leitura bem-sucedida FEITA DEPOIS do prazo que não mostre execução nova.
  const [pending, setPending] = useState<{ known: string[]; until: number; certain: boolean } | null>(null);
  const [refreshFailed, setRefreshFailed] = useState(false);
  const alive = useRef(true);
  const seq = useRef(0);   // cada leitura leva um número: só a MAIS RECENTE pode atualizar a tela (uma resposta lenta e antiga nunca esconde um teste ativo nem reabilita os botões)

  // uma leitura que falha NÃO apaga o que a tela já sabe: só a primeira carga vira erro; depois disso a tela avisa e tenta de novo
  const hasData = useRef(false);
  const keepOrFail = useCallback((code: string) => {
    if (code === "session" || code === "disabled" || code === "not_found") { setPending(null); setRefreshFailed(false); setLoad({ kind: "error", code }); return; }   // não se recupera sozinho: para de consultar e diz o que fazer
    if (hasData.current) setRefreshFailed(true);
    else setLoad({ kind: "error", code });
  }, []);

  const fetchAll = useCallback(async (signal?: AbortSignal) => {
    const mine = ++seq.current;
    const startedAt = Date.now();
    try {
      const r = await fetch(`/bff/cpes/${cpeId}/speed`, { cache: "no-store", signal });
      const j = (await r.json().catch(() => ({}))) as { caps?: unknown; runs?: unknown; error?: string };
      const caps = r.ok ? readCaps(j.caps) : null, runs = r.ok ? readRuns({ items: j.runs }) : null;
      if (!alive.current || mine !== seq.current) return;
      if (caps && runs) {
        hasData.current = true;
        setRefreshFailed(false);
        setLoad({ kind: "ready", caps, runs });
        setPending((p) => (p && (runs.some((x) => !p.known.includes(x.id)) || (!p.certain && startedAt > p.until)) ? null : p));
      } else keepOrFail(j.error && LOAD_ERROR[j.error] ? j.error : "failed");
    } catch (e) { if ((e as Error).name !== "AbortError" && alive.current && mine === seq.current) keepOrFail("failed"); }
  }, [cpeId, keepOrFail]);

  useEffect(() => { alive.current = true; const c = new AbortController(); void fetchAll(c.signal); return () => { alive.current = false; c.abort(); }; }, [fetchAll]);
  const active = load.kind === "ready" && load.runs.some((r) => ACTIVE.has(r.status));
  const following = active || pending !== null;
  useEffect(() => {   // enquanto há teste em andamento (ou um pedido ainda não confirmado pela leitura), acompanha; parado, não consulta
    if (!following) return;
    const t = setInterval(() => void fetchAll(), POLL_MS);
    return () => clearInterval(t);
  }, [following, fetchAll]);

  if (load.kind === "loading") return <p className="text-sm text-muted" data-testid="speed-loading">Carregando o teste de banda…</p>;
  if (load.kind === "error") {
    return (
      <div role="alert" className="grid gap-2 text-sm" data-testid="speed-error">
        <p className="text-danger">{LOAD_ERROR[load.code]}</p>
        {load.code === "session" && <a href="/login" className="min-h-touch w-fit rounded-btn border border-line px-3 py-2 text-accent">Entrar de novo</a>}
        {load.code === "failed" && <button type="button" onClick={() => { setLoad({ kind: "loading" }); void fetchAll(); }} className="min-h-touch w-fit rounded-btn border border-line px-3">Tentar novamente</button>}
      </div>
    );
  }
  const { caps, runs } = load;
  const dl = caps.directions.download, ul = caps.directions.upload;
  const anyOffered = dl.offered || ul.offered;
  const readyOf = (k: "CORE" | "INTERNET") => caps.endpoints.find((e) => e.target_kind === k && e.ready);
  const endpoint = readyOf(kind);
  const lastOf = (d: SpeedDirection) => runs.find((r) => r.direction === d);
  const history = runs.slice(0, 5);

  const start = async (direction: SpeedDirection) => {
    if (!endpoint || busy) return;
    setBusy(true); setRefusal(null);
    const other = lastOf(direction === "download" ? "upload" : "download");
    const group = other && other.endpoint_id === endpoint.id && other.profile === profile && !runs.some((r) => r.group_id === other.group_id && r.direction === direction) ? other.group_id : undefined;
    try {
      const r = await fetch(`/bff/cpes/${cpeId}/speed/runs`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ key: crypto.randomUUID(), direction, endpoint_id: endpoint.id, profile, ...(group ? { group_id: group } : {}) }),
      });
      const j = (await r.json().catch(() => ({}))) as { error?: string; reason?: string };
      if (r.ok) setPending({ known: runs.map((x) => x.id), until: Date.now() + PENDING_MS, certain: true });   // aceito: lembrado até uma leitura mostrar a execução
      else setRefusal(j.error === "blocked" && j.reason ? BLOCKED_TEXT[j.reason] ?? "O pedido foi recusado." : j.error === "forbidden" ? BLOCKED_TEXT.not_permitted! : "Não foi possível pedir o teste agora.");
      await fetchAll();
    } catch {   // o pedido pode ter chegado: não se sabe. Trava por pouco tempo e deixa a leitura dizer
      setPending({ known: runs.map((x) => x.id), until: Date.now() + UNCERTAIN_MS, certain: false });
      setRefusal("Não foi possível confirmar o pedido. Aguarde a atualização antes de pedir de novo.");
    } finally { setBusy(false); }
  };

  const blockedReason = !anyOffered ? (dl.reason ?? ul.reason ?? "operation_not_homologated") : null;
  return (
    <div className="grid gap-4" data-testid="speed-section">
      <p className="text-sm text-muted">Mede a WAN da ONT, não o Wi‑Fi nem a rede interna. O teste gera tráfego e consome banda do cliente; nada inicia sozinho.</p>
      {blockedReason ? (
        <div className="grid gap-2 rounded-card border border-line p-3 text-sm" data-testid="speed-blocked" data-reason={blockedReason}>
          <p className="font-medium">Teste indisponível neste aparelho</p>
          <p className="text-muted">{BLOCKED_TEXT[blockedReason] ?? "O teste não está liberado para este aparelho."}</p>
        </div>
      ) : !caps.ready ? (
        <div className="grid gap-2 rounded-card border border-line p-3 text-sm" data-testid="speed-not-ready">
          <p className="font-medium">Sem destino de teste pronto</p>
          <p className="text-muted">{caps.endpoints.length === 0 ? "Nenhum destino de teste foi cadastrado para este provedor." : "Nenhum destino respondeu à última verificação do Edge."}</p>
        </div>
      ) : (
        <>
          <fieldset className="grid gap-2" data-testid="speed-target">
            <legend className="text-sm font-medium">Destino</legend>
            <div className="flex flex-wrap gap-2">
              {(["CORE", "INTERNET"] as const).map((k) => {
                const ok = !!readyOf(k);
                return (
                  <label key={k} className={`inline-flex min-h-touch items-center gap-2 rounded-btn border px-3 text-sm ${kind === k ? "border-accent bg-bg" : "border-line"} ${ok ? "" : "opacity-50"}`}>
                    <input type="radio" name={`speed-kind-${cpeId}`} value={k} checked={kind === k} disabled={!ok} onChange={() => setKind(k)} />
                    {k === "CORE" ? "Core" : "Internet"}{!ok && <span className="text-xs text-muted"> (sem destino pronto)</span>}
                  </label>
                );
              })}
            </div>
          </fieldset>
          <div className="grid gap-1">
            <label htmlFor={`speed-profile-${cpeId}`} className="text-sm font-medium">Tamanho do arquivo</label>
            <select id={`speed-profile-${cpeId}`} value={profile} onChange={(e) => setProfile(e.target.value)} className="min-h-touch w-fit rounded-btn border border-line bg-surface px-3 text-sm">
              {caps.profiles.map((p) => <option key={p} value={p}>{PROFILE_TEXT[p] ?? p}</option>)}
            </select>
          </div>
          <div className="flex flex-wrap gap-2">
            {(["download", "upload"] as const).map((d) => (
              <button key={d} type="button" data-testid={`speed-start-${d}`} onClick={() => void start(d)} disabled={busy || active || pending !== null || !endpoint || !caps.directions[d].offered}
                className="min-h-touch rounded-btn bg-accent px-4 text-sm font-medium text-[color:var(--on-accent)] disabled:opacity-50">
                Testar {d === "download" ? "download" : "upload"}
              </button>
            ))}
          </div>
          {!dl.offered || !ul.offered ? <p className="text-xs text-muted" data-testid="speed-partial-offer">{!dl.offered ? "Download" : "Upload"}: {BLOCKED_TEXT[(!dl.offered ? dl.reason : ul.reason) ?? ""] ?? "não liberado para este aparelho."}</p> : null}
        </>
      )}
      {refusal && <p role="alert" className="text-sm text-danger" data-testid="speed-refusal">{refusal}</p>}
      {refreshFailed && <p role="status" className="text-xs text-warn" data-testid="speed-refresh-failed">Não foi possível atualizar agora. O que aparece pode estar desatualizado; tentando de novo.</p>}
      {pending && !active && (
        <div role="status" className="grid gap-2 rounded-card border border-line p-3 text-sm" data-testid="speed-pending">
          <p>{pending.certain && Date.now() > pending.until
            ? "O pedido foi aceito, mas a leitura ainda não mostra a execução. Não peça de novo: use Atualizar. Se continuar assim, chame quem administra o Edge."
            : "Pedido enviado. Aguardando a confirmação da leitura; os botões ficam travados até lá."}</p>
          <button type="button" onClick={() => void fetchAll()} data-testid="speed-pending-refresh" className="min-h-touch w-fit rounded-btn border border-line px-3">Atualizar agora</button>
        </div>
      )}
      {active && (
        <div role="status" className="rounded-card border border-line p-3 text-sm" data-testid="speed-active">
          {runs.filter((r) => ACTIVE.has(r.status)).map((r) => <p key={r.id}>{DIRECTION_TEXT[r.direction]}: {STATUS_TEXT[r.status]}</p>)}
        </div>
      )}
      <div className="grid grid-cols-2 gap-3" data-testid="speed-kpis">
        <Kpi title="Download" run={lastOf("download")} />
        <Kpi title="Upload" run={lastOf("upload")} />
      </div>
      {history.length > 0 && (
        <details data-testid="speed-history" className="text-sm">
          <summary className="min-h-touch cursor-pointer py-2">Últimos testes ({history.length})</summary>
          <ul className="grid gap-2">
            {history.map((r) => (
              <li key={r.id} className="rounded-card border border-line p-2" data-testid="speed-history-row">
                <p className="font-medium">{DIRECTION_TEXT[r.direction]} · {r.status === "completed" || r.status === "partial" ? mbpsText(r.mbps) : STATUS_TEXT[r.status] ?? "—"} <span className="font-normal text-muted">· {qualityText(r)}</span></p>
                <p className="text-xs text-muted">{when(r.created_at)} · destino {r.endpoint_id} · {PROFILE_TEXT[r.profile] ?? r.profile}{r.duration_ms ? ` · ${(r.duration_ms / 1000).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} s` : ""}</p>
                {r.reason && <p className="text-xs text-muted">{REASON_TEXT[r.reason] ?? "Sem detalhe adicional."}</p>}
              </li>
            ))}
          </ul>
        </details>
      )}
      <Link href="/ajuda/rede/testar-banda" className="text-xs text-accent underline underline-offset-2">Como o teste de banda funciona</Link>
    </div>
  );
}
