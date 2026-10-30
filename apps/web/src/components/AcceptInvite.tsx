"use client";

import Link from "next/link";
import { useState } from "react";
import { PasswordField, strength } from "@/components/PasswordField";
import { INVITE_ERROR } from "@/lib/team";

type Props = { token: string; purpose: "invite" | "reset"; accountExists: boolean; email: string; defaultName: string | null };

/** A pessoa convidada cria a conta (nome + senha), entra com a senha que já tem, ou define a nova senha de um link de redefinição. */
export function AcceptInvite({ token, purpose, accountExists, email, defaultName }: Props) {
  const [pw, setPw] = useState("");
  const [again, setAgain] = useState("");
  const [name, setName] = useState(defaultName ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const reset = purpose === "reset";
  const creating = !accountExists && !reset;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!accountExists && pw !== again) { setError(INVITE_ERROR.mismatch); return; }
    if (!accountExists && !strength(pw).ok) { setError(INVITE_ERROR.password_short); return; }
    setBusy(true);
    try {
      const res = await fetch(`/bff/invites/${token}/accept`, { method: "POST", headers: { "content-type": "application/json" }, cache: "no-store", body: JSON.stringify({ name: creating ? name : undefined, password: pw }) });
      const j = (await res.json().catch(() => ({}))) as { error?: string };
      if (res.ok) { setDone(true); return; }
      setError(INVITE_ERROR[j.error ?? "failed"] ?? INVITE_ERROR.failed);
    } catch { setError(INVITE_ERROR.failed); } finally { setBusy(false); }
  }

  if (done) {
    return (
      <div className="grid gap-4 text-sm" data-testid="accept-done" role="status">
        <p className="text-base font-medium">{reset ? "Senha trocada." : accountExists ? "Pronto, você já faz parte da equipe." : "Conta criada."}</p>
        <p className="text-muted">{reset ? "Entre com a nova senha." : "Agora é só entrar."}</p>
        <Link href="/login" className="inline-flex min-h-touch items-center justify-center rounded-btn bg-accent px-4 font-medium text-[color:var(--on-accent)]">Ir para o login</Link>
      </div>
    );
  }
  return (
    <form onSubmit={submit} className="grid gap-4 text-sm" data-testid="accept-form">
      <p className="text-muted">{creating ? <>Você entra com <strong className="text-text">{email}</strong>. Escolha seu nome e uma senha.</> : accountExists ? <>Você já tem conta com <strong className="text-text">{email}</strong>. Digite a sua senha atual para aceitar.</> : <>Escolha a nova senha de <strong className="text-text">{email}</strong>.</>}</p>
      {error && <p role="alert" data-testid="accept-error" className="text-danger">{error}</p>}
      {creating && <label className="grid gap-1">Nome completo<input name="name" required maxLength={100} value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" className="min-h-touch rounded-btn border border-line bg-bg px-3" /></label>}
      <PasswordField name="password" label={accountExists ? "Sua senha atual" : reset ? "Nova senha" : "Senha"} value={pw} onChange={setPw} autoComplete={accountExists ? "current-password" : "new-password"} showStrength={!accountExists} />
      {!accountExists && <PasswordField name="again" label="Repita a senha" value={again} onChange={setAgain} autoComplete="new-password" />}
      <button type="submit" disabled={busy} className="min-h-touch rounded-btn bg-accent px-4 font-medium text-[color:var(--on-accent)] disabled:opacity-60">
        {busy ? "Enviando…" : creating ? "Criar minha conta" : accountExists ? "Aceitar convite" : "Trocar a senha"}
      </button>
    </form>
  );
}
