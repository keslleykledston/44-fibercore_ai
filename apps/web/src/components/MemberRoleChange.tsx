"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { EntityDetailDrawer } from "@/components/EntityDetailDrawer";
import { MfaStepUp } from "@/components/MfaStepUp";
import { ROLE_CHANGE_ERROR, roleLabel } from "@/lib/roles";

/** Troca do papel de OUTRA pessoa: só os papéis que o seu papel pode atribuir; a API revalida tudo. */
export function MemberRoleChange({ userId, name, current, options }: { userId: string; name: string; current: string; options: string[] }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [needStepUp, setNeedStepUp] = useState(false);
  const last = useRef<{ role: string; reason: string } | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const router = useRouter();
  const choices = options.filter((r) => r !== current);
  const close = () => { setOpen(false); setError(null); setNeedStepUp(false); trigger.current?.focus(); };

  async function send(payload: { role: string; reason: string }) {
    setBusy(true); setError(null);
    try {
      const res = await fetch(`/bff/members/${userId}/role`, {
        method: "POST", headers: { "content-type": "application/json" }, cache: "no-store", body: JSON.stringify(payload),
      });
      const j = await res.json().catch(() => ({}));
      if (res.ok) { setOpen(false); setNeedStepUp(false); router.refresh(); return; }
      if ((j as { error?: string }).error === "mfa_recent_required") { setNeedStepUp(true); return; }
      setError(ROLE_CHANGE_ERROR[(j as { error?: string }).error ?? "failed"] ?? ROLE_CHANGE_ERROR.failed);
    } catch { setError(ROLE_CHANGE_ERROR.failed); } finally { setBusy(false); }
  }

  function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    last.current = { role: String(fd.get("role") ?? ""), reason: String(fd.get("reason") ?? "").trim() };
    void send(last.current);
  }

  return (
    <>
      <button ref={trigger} type="button" data-testid="role-change-open" aria-haspopup="dialog" onClick={() => setOpen(true)}
        className="min-h-touch rounded-btn border border-line px-3 text-sm hover:bg-bg">Alterar papel</button>
      <EntityDetailDrawer open={open} onClose={close} title={`Alterar o papel de ${name}`}>
        <form onSubmit={submit} className="grid gap-4 text-sm" data-testid="role-change-form">
          <div role="note" className="rounded-btn border border-line bg-bg p-3">
            <p className="font-medium">O que acontece</p>
            <ul className="mt-1 list-disc pl-5 text-muted">
              <li>O papel atual é <strong>{roleLabel(current)}</strong>.</li>
              <li>As sessões abertas de {name} são encerradas agora, em todos os workspaces da conta; a pessoa entra de novo com o novo papel.</li>
              <li>A mudança e o motivo ficam registrados no histórico, com o seu nome.</li>
            </ul>
          </div>
          {error && <p role="alert" data-testid="role-change-error" className="text-danger">{error}</p>}
          {choices.length === 0 ? <p className="text-muted">Seu papel não tem outro papel para atribuir a esta pessoa.</p> : (
            <>
              <label className="grid gap-1">Novo papel
                <select name="role" required defaultValue="" className="min-h-touch rounded-btn border border-line bg-bg px-3">
                  <option value="" disabled>Escolha…</option>
                  {choices.map((r) => <option key={r} value={r}>{roleLabel(r)}</option>)}
                </select>
              </label>
              <label className="grid gap-1">Motivo (3 a 200 caracteres)
                <textarea name="reason" required minLength={3} maxLength={200} rows={3} className="rounded-btn border border-line bg-bg p-3" />
              </label>
              <button type="submit" disabled={busy} className="min-h-touch rounded-btn bg-accent px-4 font-medium text-[color:var(--on-accent)] disabled:opacity-60">{busy ? "Alterando…" : "Alterar papel"}</button>
            </>
          )}
        </form>
        {needStepUp && <div className="mt-4"><MfaStepUp onDone={() => last.current && void send(last.current)} /></div>}
      </EntityDetailDrawer>
    </>
  );
}
