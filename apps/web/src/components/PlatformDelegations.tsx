"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { MfaStepUp } from "@/components/MfaStepUp";
import { DELEGATION_ERROR } from "@/lib/roles";

type Action = { kind: "grant"; body: { email: string; reason: string; hours: string } } | { kind: "revoke"; id: string };

/** Acesso temporário do suporte da plataforma (ADR-0031): conceder com prazo e motivo, ou encerrar agora. A API decide; aqui só a interface. */
export function PlatformDelegations({ canDelegate, maxHours }: { canDelegate: boolean; maxHours: number }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [needStepUp, setNeedStepUp] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const pending = useRef<Action | null>(null);
  const form = useRef<HTMLFormElement>(null);

  async function run(a: Action) {
    setBusy(true); setError(null); setDone(null);
    try {
      const res = a.kind === "grant"
        ? await fetch("/bff/platform-delegations", { method: "POST", headers: { "content-type": "application/json" }, cache: "no-store", body: JSON.stringify(a.body) })
        : await fetch(`/bff/platform-delegations/${a.id}`, { method: "POST", cache: "no-store" });
      const j = await res.json().catch(() => ({}));
      if (res.ok) { setNeedStepUp(false); setDone(a.kind === "grant" ? "Acesso concedido." : "Acesso encerrado."); if (a.kind === "grant") form.current?.reset(); router.refresh(); return; }
      if ((j as { error?: string }).error === "mfa_recent_required") { setNeedStepUp(true); return; }
      setError(DELEGATION_ERROR[(j as { error?: string }).error ?? "failed"] ?? DELEGATION_ERROR.failed);
    } catch { setError(DELEGATION_ERROR.failed); } finally { setBusy(false); }
  }
  const start = (a: Action) => { pending.current = a; void run(a); };

  if (!canDelegate) return null;
  return (
    <div className="grid gap-3">
      <form ref={form} data-testid="delegation-form" className="panel grid gap-3 p-4 text-sm" onSubmit={(e) => {
        e.preventDefault();
        const fd = new FormData(e.currentTarget);
        start({ kind: "grant", body: { email: String(fd.get("email") ?? "").trim(), reason: String(fd.get("reason") ?? "").trim(), hours: String(fd.get("hours") ?? "") } });
      }}>
        <p className="text-muted">O suporte da plataforma só <strong>consulta</strong> (dados básicos do workspace; nenhum dado de cliente) e perde o acesso sozinho no prazo. Quem pode receber é só uma conta que a própria plataforma marcou como operadora.</p>
        <label className="grid gap-1">E-mail do operador da plataforma
          <input name="email" type="email" required maxLength={254} className="min-h-touch rounded-btn border border-line bg-bg px-3" />
        </label>
        <label className="grid gap-1">Motivo (10 a 300 caracteres, ex.: número do chamado)
          <textarea name="reason" required minLength={10} maxLength={300} rows={2} className="rounded-btn border border-line bg-bg p-3" />
        </label>
        <label className="grid gap-1">Prazo
          <select name="hours" defaultValue={String(maxHours)} className="min-h-touch rounded-btn border border-line bg-bg px-3">
            {Array.from({ length: maxHours }, (_, i) => i + 1).map((h) => <option key={h} value={h}>{h} {h === 1 ? "hora" : "horas"}</option>)}
          </select>
        </label>
        {error && <p role="alert" data-testid="delegation-error" className="text-danger">{error}</p>}
        {done && <p role="status" data-testid="delegation-done">{done}</p>}
        <button type="submit" disabled={busy} className="min-h-touch rounded-btn bg-accent px-4 font-medium text-[color:var(--on-accent)] disabled:opacity-60">{busy ? "Concedendo…" : "Conceder acesso"}</button>
      </form>
      {needStepUp && <MfaStepUp onDone={() => pending.current && void run(pending.current)} />}
    </div>
  );
}

/** Botão de encerrar de uma linha da tabela; usa o mesmo fluxo (inclusive a confirmação do segundo fator). */
export function RevokeDelegation({ id, who }: { id: string; who: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [needStepUp, setNeedStepUp] = useState(false);

  async function revoke() {
    setBusy(true); setError(null);
    try {
      const res = await fetch(`/bff/platform-delegations/${id}`, { method: "POST", cache: "no-store" });
      const j = await res.json().catch(() => ({}));
      if (res.ok) { setNeedStepUp(false); router.refresh(); return; }
      if ((j as { error?: string }).error === "mfa_recent_required") { setNeedStepUp(true); return; }
      setError(DELEGATION_ERROR[(j as { error?: string }).error ?? "failed"] ?? DELEGATION_ERROR.failed);
    } catch { setError(DELEGATION_ERROR.failed); } finally { setBusy(false); }
  }
  return (
    <div className="grid justify-items-end gap-2">
      <button type="button" disabled={busy} onClick={() => void revoke()} data-testid="delegation-revoke" aria-label={`Encerrar o acesso de ${who}`}
        className="min-h-touch rounded-btn border border-line px-3 text-sm hover:bg-bg disabled:opacity-60">Encerrar agora</button>
      {error && <p role="alert" className="text-xs text-danger">{error}</p>}
      {needStepUp && <MfaStepUp onDone={() => void revoke()} />}
    </div>
  );
}
