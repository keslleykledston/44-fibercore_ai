"use client";

import Link from "next/link";
import { useState } from "react";
import { PasswordField, strength } from "@/components/PasswordField";
import { INVITE_ERROR } from "@/lib/team";

const MSG: Record<string, string> = { ...INVITE_ERROR, password_same: "A nova senha precisa ser diferente da atual.", session: "Sua sessão expirou. Entre de novo." };

/** Trocar a PRÓPRIA senha. Ao terminar, todas as sessões da conta acabam e a pessoa entra de novo. */
export function ChangePassword() {
  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault(); setError(null);
    if (next !== again) { setError(INVITE_ERROR.mismatch); return; }
    if (!strength(next).ok) { setError(INVITE_ERROR.password_short); return; }
    setBusy(true);
    try {
      const res = await fetch("/bff/account/password", { method: "POST", headers: { "content-type": "application/json" }, cache: "no-store", body: JSON.stringify({ current: cur, next }) });
      const j = (await res.json().catch(() => ({}))) as { error?: string };
      if (res.ok) { setDone(true); return; }
      setError(MSG[j.error ?? "failed"] ?? MSG.failed);
    } catch { setError(MSG.failed); } finally { setBusy(false); }
  }
  if (done) return <div role="status" className="panel grid gap-3 p-4 text-sm" data-testid="password-done"><p className="font-medium">Senha trocada.</p><p className="text-muted">Por segurança, todas as sessões foram encerradas. Entre de novo com a nova senha.</p><Link href="/login" className="inline-flex min-h-touch items-center text-accent hover:underline">Ir para o login</Link></div>;
  return (
    <form onSubmit={submit} className="panel grid gap-4 p-4 text-sm" data-testid="password-form" aria-labelledby="h-pass">
      <h2 id="h-pass" className="text-base font-semibold">Trocar a senha</h2>
      {error && <p role="alert" data-testid="password-error" className="text-danger">{error}</p>}
      <PasswordField name="current" label="Senha atual" value={cur} onChange={setCur} autoComplete="current-password" />
      <PasswordField name="next" label="Nova senha" value={next} onChange={setNext} autoComplete="new-password" showStrength />
      <PasswordField name="again" label="Repita a nova senha" value={again} onChange={setAgain} autoComplete="new-password" />
      <button type="submit" disabled={busy} className="min-h-touch rounded-btn bg-accent px-4 font-medium text-[color:var(--on-accent)] disabled:opacity-60">{busy ? "Trocando…" : "Trocar a senha"}</button>
    </form>
  );
}
