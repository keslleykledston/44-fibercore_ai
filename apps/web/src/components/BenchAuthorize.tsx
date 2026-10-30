"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { EntityDetailDrawer } from "@/components/EntityDetailDrawer";
import { MfaStepUp } from "@/components/MfaStepUp";
import { BENCH_ERROR, BENCH_OP_LABEL } from "@/lib/devices";
import type { BenchAuthorizations } from "@/lib/types";

const when = (iso: string) => new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short", timeZone: "America/Sao_Paulo" });
const STATE: Record<string, string> = { open: "Aberta", consumed: "Usada", revoked: "Encerrada" };

type Pending = { kind: "grant"; body: Record<string, unknown> } | { kind: "revoke"; id: string };

/** Autorização PRÉVIA de uma manobra de bancada: uso único, curta, só o alvo de bancada. Quem autoriza não pode ser quem pede nem quem aprova. */
export function BenchAuthorize({ cpeId, data }: { cpeId: string; data: BenchAuthorizations }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [needStepUp, setNeedStepUp] = useState(false);
  const [op, setOp] = useState(data.operations[0] ?? "");
  const pending = useRef<Pending | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const close = () => { setOpen(false); setError(null); setNeedStepUp(false); trigger.current?.focus(); };

  async function run(a: Pending) {
    setBusy(true); setError(null);
    try {
      const res = a.kind === "grant"
        ? await fetch("/bff/bench/authorizations", { method: "POST", headers: { "content-type": "application/json" }, cache: "no-store", body: JSON.stringify(a.body) })
        : await fetch(`/bff/bench/authorizations/${a.id}`, { method: "POST", cache: "no-store" });
      const j = (await res.json().catch(() => ({}))) as { error?: string };
      if (res.ok) { setNeedStepUp(false); setOpen(false); router.refresh(); return; }
      if (j.error === "mfa_recent_required") { setNeedStepUp(true); return; }
      setError(BENCH_ERROR[j.error ?? "failed"] ?? BENCH_ERROR.failed);
    } catch { setError(BENCH_ERROR.failed); } finally { setBusy(false); }
  }
  const start = (a: Pending) => { pending.current = a; void run(a); };

  return (
    <div className="grid gap-3 text-sm">
      {data.can_authorize && data.operations.length > 0 && (
        <div>
          <button ref={trigger} type="button" onClick={() => setOpen(true)} aria-haspopup="dialog" data-testid="bench-open"
            className="min-h-touch rounded-btn border border-line px-3 hover:bg-bg">Autorizar uma manobra…</button>
        </div>
      )}
      {error && !open && <p role="alert" className="text-danger">{error}</p>}
      {data.items.length === 0 ? <p className="text-muted">Nenhuma autorização registrada para este equipamento.</p> : (
        <ul className="divide-y divide-line" data-testid="bench-list">
          {data.items.map((a) => (
            <li key={a.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <div>
                <div className="font-medium">{BENCH_OP_LABEL[a.operation] ?? a.operation}</div>
                <div className="text-xs text-muted">
                  {a.live ? "Aberta, vale até " : `${STATE[a.state] ?? a.state}${a.state === "open" ? " (venceu)" : ""} · até `}{when(a.window_end)} · {a.via === "api" ? `dada pelo painel${a.by ? ` por ${a.by}` : a.mine ? " por você" : ""}` : "gravada pelo responsável no servidor"}
                </div>
              </div>
              {a.live && a.via === "api" && data.can_authorize && (
                <button type="button" disabled={busy} onClick={() => start({ kind: "revoke", id: a.id })} data-testid="bench-revoke"
                  className="min-h-touch rounded-btn border border-line px-3 hover:bg-bg disabled:opacity-60">Encerrar</button>
              )}
            </li>
          ))}
        </ul>
      )}
      <EntityDetailDrawer open={open} onClose={close} title="Autorizar uma manobra de bancada">
        <form onSubmit={(e) => {
          e.preventDefault();
          const fd = new FormData(e.currentTarget);
          start({ kind: "grant", body: { cpe_id: cpeId, operation: op, ssid: op === "set_wifi_ssid" ? String(fd.get("ssid") ?? "").trim() : undefined, minutes: Number(fd.get("minutes")) } });
        }} className="grid gap-4" data-testid="bench-form">
          <div role="note" className="rounded-btn border border-line bg-bg p-3">
            <p className="font-medium">O que isto faz</p>
            <ul className="mt-1 list-disc pl-5 text-muted">
              <li>Registra a autorização <strong>prévia</strong> de <strong>uma</strong> manobra neste equipamento de bancada. Ela vale uma vez só e vence no tempo escolhido.</li>
              <li>Não executa nada. Alguém ainda pede a manobra e ela é aprovada em Operações.</li>
              <li><strong>Você não pode ser quem pede nem quem aprova</strong> a manobra que autorizou: o sistema recusa.</li>
            </ul>
          </div>
          {error && <p role="alert" data-testid="bench-error" className="text-danger">{error}</p>}
          <label className="grid gap-1">Manobra
            <select value={op} onChange={(e) => setOp(e.target.value)} className="min-h-touch rounded-btn border border-line bg-bg px-3">
              {data.operations.map((o) => <option key={o} value={o}>{BENCH_OP_LABEL[o] ?? o}</option>)}
            </select>
          </label>
          {op === "set_wifi_ssid" && (
            <label className="grid gap-1">Novo nome do Wi-Fi (começa com BANCADA-)
              <input name="ssid" required pattern="BANCADA-[A-Z0-9]{1,16}" maxLength={25} className="min-h-touch rounded-btn border border-line bg-bg px-3 font-mono" />
            </label>
          )}
          <label className="grid gap-1">Validade
            <select name="minutes" defaultValue="30" className="min-h-touch rounded-btn border border-line bg-bg px-3">
              {[15, 30, 60, 120].map((m) => <option key={m} value={m}>{m} minutos</option>)}
            </select>
          </label>
          <button type="submit" disabled={busy} className="min-h-touch rounded-btn bg-accent px-4 font-medium text-[color:var(--on-accent)] disabled:opacity-60">{busy ? "Autorizando…" : "Autorizar"}</button>
        </form>
        {needStepUp && <div className="mt-4"><MfaStepUp onDone={() => pending.current && void run(pending.current)} /></div>}
      </EntityDetailDrawer>
      {needStepUp && !open && <MfaStepUp onDone={() => pending.current && void run(pending.current)} />}
    </div>
  );
}
