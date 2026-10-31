"use client";

import { useEffect, useState } from "react";
import { humanHours } from "@/lib/offline";
import type { OnuHistory } from "@/lib/types";

type St = { kind: "loading" } | { kind: "ready"; h: OnuHistory } | { kind: "error"; code: string };
const STATE: Record<string, string> = { online: "online", offline: "fora do ar", los: "sem sinal (LOS)", dying_gasp: "falta de energia", unknown: "desconhecido" };
const ERR: Record<string, string> = { forbidden: "Seu papel não permite ver o histórico.", disabled: "O painel de gestão está desligado para este provedor.", not_found: "Esta ONU não existe mais.", session: "Sua sessão expirou. Recarregue a página e entre de novo." };
const when = (iso: string) => new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });

/** Aba Histórico: o que o Edge observou nos últimos 30 dias (queda e volta entre duas coletas não aparecem). Somente leitura. */
export function OnuHistoryTab({ onuId }: { onuId: string }) {
  const [st, setSt] = useState<St>({ kind: "loading" });
  const [tries, setTries] = useState(0);
  useEffect(() => {
    const ctl = new AbortController();
    setSt({ kind: "loading" });
    fetch(`/bff/onus/${onuId}/history`, { cache: "no-store", signal: ctl.signal }).then(async (r) => {
      const j = (await r.json().catch(() => ({}))) as { history?: OnuHistory; error?: string };
      const h = j.history;
      const ok = r.ok && h && h.onu_id?.toLowerCase() === onuId.toLowerCase() && h.summary && Array.isArray(h.events);
      setSt(ok ? { kind: "ready", h: h as OnuHistory } : { kind: "error", code: j.error && ERR[j.error] ? j.error : "failed" });
    }).catch((e) => { if ((e as Error).name !== "AbortError") setSt({ kind: "error", code: "failed" }); });
    return () => ctl.abort();
  }, [onuId, tries]);
  if (st.kind === "loading") return <p className="text-sm text-muted" data-testid="onu-history-loading">Carregando o histórico…</p>;
  if (st.kind === "error") {
    return (
      <div role="alert" data-testid="onu-history-error" className="grid gap-2 text-sm">
        <p className="text-danger">{ERR[st.code] ?? "O histórico não está disponível agora."}</p>
        {!ERR[st.code] && <button type="button" onClick={() => setTries((n) => n + 1)} className="min-h-touch w-fit rounded-btn border border-line px-3">Tentar novamente</button>}
      </div>
    );
  }
  const { summary: s, events } = st.h;
  return (
    <div className="grid gap-4 text-sm" data-testid="onu-history">
      <dl className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-1">
        <dt className="text-muted">Quedas (30 dias)</dt><dd data-testid="onu-history-drops">{s.drops}</dd>
        <dt className="text-muted">Tempo fora do ar</dt><dd>{humanHours(s.offline_hours)}</dd>
        <dt className="text-muted">Disponibilidade</dt><dd>{s.availability_pct === null ? "—" : `${s.availability_pct.toLocaleString("pt-BR")}%`}</dd>
      </dl>
      <ol className="divide-y divide-line" aria-label="Mudanças de estado, da mais recente para a mais antiga">
        {events.map((e) => (
          <li key={e.id} className="py-1.5">
            <span className="font-medium">{e.baseline ? `Primeira observação: ${STATE[e.to] ?? e.to}` : e.to === "online" ? "Voltou a ficar online" : e.to === "unknown" ? "Estado deixou de ser conhecido" : `Ficou ${STATE[e.to] ?? e.to}`}</span>
            <span className="block text-xs text-muted">{when(e.at)}</span>
          </li>
        ))}
        {events.length === 0 && <li className="py-1.5 text-muted">Nenhuma mudança de estado observada.</li>}
      </ol>
      <p className="text-xs text-muted">Conta o que o Edge observou: uma queda e a volta entre duas coletas não aparecem. {st.h.truncated ? "Mostrando as mais recentes." : ""}</p>
    </div>
  );
}
