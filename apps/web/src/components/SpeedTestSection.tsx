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
  const alive = useRef(true);
  const seq = useRef(0);   // cada leitura leva um número: só a MAIS RECENTE pode atualizar a tela (uma resposta lenta e antiga nunca esconde um teste ativo nem reabilita os botões)

  const fetchAll = useCallback(async (signal?: AbortSignal) => {
    const mine = ++seq.current;
    try {
      const r = await fetch(`/bff/cpes/${cpeId}/speed`, { cache: "no-store", signal });
      const j = (await r.json().catch(() => ({}))) as { caps?: unknown; runs?: unknown; error?: string };
      const caps = r.ok ? readCaps(j.caps) : null, runs = r.ok ? readRuns({ items: j.runs }) : null;
      if (!alive.current || mine !== seq.current) return;
      setLoad(caps && runs ? { kind: "ready", caps, runs } : { kind: "error", code: j.error && LOAD_ERROR[j.error] ? j.error : "failed" });
    } catch (e) { if ((e as Error).name !== "AbortError" && alive.current && mine === seq.current) setLoad({ kind: "error", code: "failed" }); }
  }, [cpeId]);

  useEffect(() => { alive.current = true; const c = new AbortController(); void fetchAll(c.signal); return () => { alive.current = false; c.abort(); }; }, [fetchAll]);
  const active = load.kind === "ready" && load.runs.some((r) => ACTIVE.has(r.status));
  useEffect(() => {   // enquanto há teste em andamento, acompanha; parado, não consulta
    if (!active) return;
    const t = setInterval(() => void fetchAll(), POLL_MS);
    return () => clearInterval(t);
  }, [active, fetchAll]);

  if (load.kind === "loading") return <p className="text-sm text-muted" data-testid="speed-loading">Carregando o teste de banda…</p>;
  if (load.kind === "error") {
    return (
      <div role="alert" className="grid gap-2 text-sm" data-testid="speed-error">
        <p className="text-danger">{LOAD_ERROR[load.code]}</p>
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
      if (!r.ok) setRefusal(j.error === "blocked" && j.reason ? BLOCKED_TEXT[j.reason] ?? "O pedido foi recusado." : j.error === "forbidden" ? BLOCKED_TEXT.not_permitted! : "Não foi possível pedir o teste agora.");
      await fetchAll();
    } catch { setRefusal("Não foi possível pedir o teste agora."); } finally { setBusy(false); }
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
              <button key={d} type="button" data-testid={`speed-start-${d}`} onClick={() => void start(d)} disabled={busy || active || !endpoint || !caps.directions[d].offered}
                className="min-h-touch rounded-btn bg-accent px-4 text-sm font-medium text-[color:var(--on-accent)] disabled:opacity-50">
                Testar {d === "download" ? "download" : "upload"}
              </button>
            ))}
          </div>
          {!dl.offered || !ul.offered ? <p className="text-xs text-muted" data-testid="speed-partial-offer">{!dl.offered ? "Download" : "Upload"}: {BLOCKED_TEXT[(!dl.offered ? dl.reason : ul.reason) ?? ""] ?? "não liberado para este aparelho."}</p> : null}
        </>
      )}
      {refusal && <p role="alert" className="text-sm text-danger" data-testid="speed-refusal">{refusal}</p>}
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
