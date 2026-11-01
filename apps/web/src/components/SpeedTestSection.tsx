"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ACTIVE, BLOCKED_TEXT, DIRECTION_TEXT, mbpsText, PROFILE_TEXT, PROFILES, qualityText, REASON_TEXT, STATUS_TEXT,
  type SpeedCaps, type SpeedDirection, type SpeedRun, readCaps, readRuns,
} from "@/lib/speed";

type Load = { kind: "loading" } | { kind: "error"; code: string } | { kind: "ready"; caps: SpeedCaps; runs: SpeedRun[] };
const LOAD_ERROR: Record<string, string> = {
  disabled: "O teste de banda está desligado para este provedor.", not_found: "Este aparelho não existe mais.", session: "Sua sessão expirou. Recarregue a página e entre de novo.",
  failed: "Não foi possível carregar o teste de banda agora.",
};
const when = (iso: string) => new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
// Marcador de pedido em curso, por aparelho, que sobrevive a fechar o painel, trocar de aba e recarregar (sessão do navegador): remontar a seção não pode reabrir o botão sobre um pedido ainda não
// esclarecido, e cada clique leva uma chave de idempotência nova, então só a trava impede um segundo tráfego.
// `runId` = a API respondeu sucesso e disse QUAL execução criou: só uma leitura que mostre ESSA execução destrava (a de outra pessoa não prova nada), nunca o relógio. Sem `runId` (resposta perdida, ou 2xx
// sem o id) o pedido é INCERTO e nunca se resolve por tempo: "Confirmar pedido" repete o MESMO pedido com a MESMA chave de idempotência, e a API responde com a execução já criada ou cria a única que faltava
// (nunca duas). Uma recusa definitiva na confirmação limpa a trava.
type Req = { direction: SpeedDirection; endpoint_id: string; profile: string; group_id?: string };   // o pedido fica junto da chave: repetir é repetir a MESMA intenção
type Pending = { runId: string | null; key: string; req: Req };
const memo = new Map<string, Pending | null>();
const KEY = (cpe: string) => `fc-speed-pending:${cpe}`;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
function readPending(cpe: string): Pending | null {
  if (memo.has(cpe)) return memo.get(cpe) ?? null;
  try {
    const raw = window.sessionStorage.getItem(KEY(cpe));
    const o = raw ? (JSON.parse(raw) as Pending) : null;
    const q = o?.req;
    const ok = !!o && (o.runId === null || typeof o.runId === "string") && typeof o.key === "string" && /^[A-Za-z0-9_.:-]{8,128}$/.test(o.key) && !!q
      && (q.direction === "download" || q.direction === "upload") && typeof q.endpoint_id === "string" && /^[a-z0-9][a-z0-9-]{1,30}$/.test(q.endpoint_id)
      && typeof q.profile === "string" && (PROFILES as readonly string[]).includes(q.profile) && (q.group_id === undefined || (typeof q.group_id === "string" && UUID.test(q.group_id)));
    memo.set(cpe, ok ? o : null);
  } catch { memo.set(cpe, null); }
  return memo.get(cpe) ?? null;
}
/** false = o navegador NÃO guardou a trava (armazenamento bloqueado/cheio): quem chama não pode enviar um pedido novo, porque um recarregamento perderia a chave de um pedido incerto. */
function writePending(cpe: string, p: Pending | null): boolean {
  memo.set(cpe, p);
  try {
    if (p) window.sessionStorage.setItem(KEY(cpe), JSON.stringify(p)); else window.sessionStorage.removeItem(KEY(cpe));
    return true;
  } catch { return false; }
}

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
  // Um pedido é lembrado à parte do último retrato das execuções: se a leitura seguinte falha ou chega velha, a tela continua dizendo que há um pedido em curso e os botões continuam travados
  // (senão um novo clique geraria outro tráfego). Ver o protocolo (`runId`, chave, "Confirmar pedido") no comentário do marcador acima.
  const [pending, setPendingState] = useState<Pending | null>(() => (typeof window === "undefined" ? null : readPending(cpeId)));
  const setPending = useCallback((next: Pending | null | ((p: Pending | null) => Pending | null)) => {
    setPendingState((prev) => { const v = typeof next === "function" ? next(prev) : next; writePending(cpeId, v); return v; });
  }, [cpeId]);
  const [refreshFailed, setRefreshFailed] = useState(false);
  const alive = useRef(true);
  const seq = useRef(0);   // cada leitura leva um número: só a MAIS RECENTE pode atualizar a tela (uma resposta lenta e antiga nunca esconde um teste ativo nem reabilita os botões)

  // uma leitura que falha NÃO apaga o que a tela já sabe: só a primeira carga vira erro; depois disso a tela avisa e tenta de novo
  const hasData = useRef(false);
  const keepOrFail = useCallback((code: string) => {
    if (code === "session" || code === "disabled" || code === "not_found") { setRefreshFailed(false); setLoad({ kind: "error", code }); return; }   // não se recupera sozinho: para de consultar e diz o que fazer (o marcador de pedido em curso é GUARDADO: o travamento não some com o erro)
    if (hasData.current) setRefreshFailed(true);
    else setLoad({ kind: "error", code });
  }, []);

  const fetchAll = useCallback(async (signal?: AbortSignal) => {
    const mine = ++seq.current;
    try {
      const r = await fetch(`/bff/cpes/${cpeId}/speed`, { cache: "no-store", signal });
      const j = (await r.json().catch(() => ({}))) as { caps?: unknown; runs?: unknown; error?: string };
      const caps = r.ok ? readCaps(j.caps) : null, runs = r.ok ? readRuns({ items: j.runs }) : null;
      if (!alive.current || mine !== seq.current) return;
      if (caps && runs) {
        hasData.current = true;
        setRefreshFailed(false);
        setLoad({ kind: "ready", caps, runs });
        setPending((p) => (p && p.runId && runs.some((x) => x.id === p.runId) ? null : p));   // só a execução DESTE pedido destrava
      } else keepOrFail(j.error && LOAD_ERROR[j.error] ? j.error : "failed");
    } catch (e) { if ((e as Error).name !== "AbortError" && alive.current && mine === seq.current) keepOrFail("failed"); }
  }, [cpeId, keepOrFail, setPending]);

  useEffect(() => { alive.current = true; const c = new AbortController(); void fetchAll(c.signal); return () => { alive.current = false; c.abort(); }; }, [fetchAll]);
  const active = load.kind === "ready" && load.runs.some((r) => ACTIVE.has(r.status));
  const following = load.kind === "ready" && (active || pending !== null);
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
  const locked = busy || active || pending !== null;

  // Um pedido, uma chave: `send` grava a trava (com a chave) ANTES do POST e só a limpa diante de recusa definitiva; repetir com a mesma chave é seguro (idempotente na API).
  const send = async (key: string, q: Req) => {
    setBusy(true); setRefusal(null);
    setPending((p) => ({ runId: p?.key === key ? p.runId : null, key, req: q }));
    try {
      const r = await fetch(`/bff/cpes/${cpeId}/speed/runs`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ key, ...q }) });
      const j = (await r.json().catch(() => ({}))) as { error?: string; reason?: string; run_id?: unknown };
      // Só estes códigos garantem, pelo contrato do BFF/API, que NADA foi criado (recusa definitiva). Qualquer outra falha (5xx, 502, resposta ilegível) é AMBÍGUA: o pedido pode ter sido gravado.
      const definitive = [400, 401, 403, 404, 409, 413].includes(r.status);
      if (r.ok) setPending({ runId: typeof j.run_id === "string" ? j.run_id : null, key, req: q });   // aceito: lembrado até uma leitura mostrar ESTA execução
      else if (!definitive) setRefusal("Não foi possível confirmar o pedido. Use Confirmar pedido: ele repete o mesmo pedido sem criar outro.");
      else {   // recusa definitiva: nada foi criado, a trava sai
        setPending(null);
        setRefusal(j.error === "blocked" && j.reason ? BLOCKED_TEXT[j.reason] ?? "O pedido foi recusado." : j.error === "forbidden" ? BLOCKED_TEXT.not_permitted! : "Não foi possível pedir o teste agora.");
      }
      await fetchAll();
    } catch {   // o pedido pode ter chegado: não se sabe; a trava (com a chave) fica
      setRefusal("Não foi possível confirmar o pedido. Use Confirmar pedido: ele repete o mesmo pedido sem criar outro.");
    } finally { setBusy(false); }
  };
  const start = (direction: SpeedDirection) => {
    if (!endpoint || locked) return;
    const other = lastOf(direction === "download" ? "upload" : "download");
    const group = other && other.endpoint_id === endpoint.id && other.profile === profile && !runs.some((r) => r.group_id === other.group_id && r.direction === direction) ? other.group_id : undefined;
    const marker: Pending = { runId: null, key: crypto.randomUUID(), req: { direction, endpoint_id: endpoint.id, profile, ...(group ? { group_id: group } : {}) } };
    if (!writePending(cpeId, marker)) {   // sem como guardar a chave, um pedido incerto não poderia ser repetido com segurança depois de recarregar: não envia
      writePending(cpeId, null);
      setRefusal("Este navegador não permite guardar o pedido em andamento, então o teste não pode ser pedido com segurança daqui. Libere o armazenamento do site ou use outro navegador.");
      return;
    }
    setPendingState(marker);
    void send(marker.key, marker.req);
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
              <button key={d} type="button" data-testid={`speed-start-${d}`} onClick={() => start(d)} disabled={locked || !endpoint || !caps.directions[d].offered}
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
          <p>{pending.runId
            ? "Pedido enviado. Aguardando a leitura mostrar a execução; os botões ficam travados até lá."
            : "Pedido enviado, mas a confirmação não chegou. Os botões ficam travados: use Confirmar pedido para repetir O MESMO pedido (a API não cria um segundo teste)."}</p>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={() => void fetchAll()} data-testid="speed-pending-refresh" className="min-h-touch w-fit rounded-btn border border-line px-3">Atualizar agora</button>
            {!pending.runId && <button type="button" onClick={() => void send(pending.key, pending.req)} disabled={busy} data-testid="speed-pending-confirm" className="min-h-touch w-fit rounded-btn border border-line px-3 text-accent">Confirmar pedido</button>}
          </div>
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
