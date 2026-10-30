"use client";

import { useState } from "react";
import { STEP_UP_ERROR } from "@/lib/roles";

/**
 * Pede o segundo fator de novo (ADR-0031, "MFA recente") sem tirar a pessoa do que estava fazendo.
 * Só o código viaja; o servidor do painel troca o cookie da sessão e a ação é repetida por quem chamou.
 */
export function MfaStepUp({ onDone }: { onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const code = String(new FormData(e.currentTarget).get("code") ?? "").trim();
    setBusy(true); setError(null);
    try {
      const res = await fetch("/bff/mfa/step-up", { method: "POST", headers: { "content-type": "application/json" }, cache: "no-store", body: JSON.stringify({ code }) });
      const j = await res.json().catch(() => ({}));
      if (res.ok) { onDone(); return; }
      setError(STEP_UP_ERROR[(j as { error?: string }).error ?? "failed"] ?? STEP_UP_ERROR.failed);
    } catch { setError(STEP_UP_ERROR.failed); } finally { setBusy(false); }
  }

  return (
    <form onSubmit={submit} data-testid="mfa-step-up" className="grid gap-3 rounded-btn border border-line bg-bg p-3 text-sm">
      <p role="status"><strong>Confirme que é você.</strong> Esta ação exige que o segundo fator tenha sido confirmado há menos de 10 minutos. Digite o código do autenticador (ou um código de recuperação).</p>
      {error && <p role="alert" data-testid="mfa-step-up-error" className="text-danger">{error}</p>}
      <label className="grid gap-1">Código do autenticador
        <input name="code" required minLength={6} maxLength={32} autoComplete="one-time-code" inputMode="numeric" className="min-h-touch rounded-btn border border-line bg-bg px-3" />
      </label>
      <button type="submit" disabled={busy} className="min-h-touch rounded-btn bg-accent px-4 font-medium text-[color:var(--on-accent)] disabled:opacity-60">{busy ? "Confirmando…" : "Confirmar e continuar"}</button>
    </form>
  );
}
