"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { EntityDetailDrawer } from "@/components/EntityDetailDrawer";
import { MfaStepUp } from "@/components/MfaStepUp";
import { SecretLink } from "@/components/SecretLink";
import { TEAM_ERROR, inviteLink } from "@/lib/team";
import type { TeamRole } from "@/lib/types";

/** Convidar uma pessoa em dois passos: quem e qual função; depois o link para enviar. */
export function InviteDrawer({ roles }: { roles: TeamRole[] }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [needStepUp, setNeedStepUp] = useState(false);
  const [role, setRole] = useState("");
  const [done, setDone] = useState<{ token: string; email: string; roleLabel: string } | null>(null);
  const last = useRef<{ email: string; name: string; role: string } | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const choices = roles.filter((r) => r.assignable_by_me);
  const close = () => { setOpen(false); setError(null); setNeedStepUp(false); if (done) router.refresh(); setDone(null); setRole(""); trigger.current?.focus(); };

  async function send(p: { email: string; name: string; role: string }) {
    setBusy(true); setError(null);
    try {
      const res = await fetch("/bff/team/invites", { method: "POST", headers: { "content-type": "application/json" }, cache: "no-store", body: JSON.stringify(p) });
      const j = (await res.json().catch(() => ({}))) as { error?: string; token?: string; email?: string; role_label?: string };
      if (res.ok && j.token) { setNeedStepUp(false); setDone({ token: j.token, email: j.email ?? p.email, roleLabel: j.role_label ?? "" }); return; }
      if (j.error === "mfa_recent_required") { setNeedStepUp(true); return; }
      setError(TEAM_ERROR[j.error ?? "failed"] ?? TEAM_ERROR.failed);
    } catch { setError(TEAM_ERROR.failed); } finally { setBusy(false); }
  }

  return (
    <>
      <button ref={trigger} type="button" onClick={() => setOpen(true)} aria-haspopup="dialog" data-testid="invite-open"
        className="min-h-touch rounded-btn bg-accent px-4 font-medium text-[color:var(--on-accent)]">Convidar pessoa</button>
      <EntityDetailDrawer open={open} onClose={close} title={done ? "Convite criado" : "Convidar pessoa"}>
        {done ? (
          <div className="grid gap-4 text-sm" data-testid="invite-done">
            <p><strong>{done.email}</strong> foi convidada como <strong>{done.roleLabel}</strong>. Ela escolhe o próprio nome e a própria senha ao abrir o link.</p>
            <SecretLink url={inviteLink(typeof window === "undefined" ? "" : window.location.origin, done.token)} validity="72 horas" title="Link do convite" />
            <button type="button" onClick={close} className="min-h-touch rounded-btn border border-line px-4">Concluir</button>
          </div>
        ) : (
          <form onSubmit={(e) => {
            e.preventDefault();
            const fd = new FormData(e.currentTarget);
            last.current = { email: String(fd.get("email") ?? "").trim(), name: String(fd.get("name") ?? "").trim(), role };
            void send(last.current);
          }} className="grid gap-4 text-sm" data-testid="invite-form">
            {error && <p role="alert" data-testid="invite-error" className="text-danger">{error}</p>}
            <label className="grid gap-1">E-mail da pessoa
              <input name="email" type="email" required maxLength={254} autoComplete="off" className="min-h-touch rounded-btn border border-line bg-bg px-3" />
            </label>
            <label className="grid gap-1">Nome <span className="text-xs text-muted">(opcional, a pessoa confirma ao entrar)</span>
              <input name="name" maxLength={100} autoComplete="off" className="min-h-touch rounded-btn border border-line bg-bg px-3" />
            </label>
            <fieldset className="grid gap-2">
              <legend className="mb-1 font-medium">Qual função?</legend>
              {choices.length === 0 ? <p className="text-muted">Seu papel não pode convidar ninguém.</p> : choices.map((r) => (
                <label key={r.role} className={`grid cursor-pointer gap-1 rounded-btn border p-3 ${role === r.role ? "border-accent bg-bg" : "border-line"}`}>
                  <span className="flex items-center gap-2">
                    <input type="radio" name="role" value={r.role} required checked={role === r.role} onChange={() => setRole(r.role)} className="size-4" />
                    <span className="font-medium">{r.label}</span>
                    {r.role === "isp_admin" && <span className="rounded-btn border border-warn px-2 text-xs">Acesso total</span>}
                  </span>
                  <span className="pl-6 text-muted">{r.summary}</span>
                  {role === r.role && (
                    <span className="grid gap-1 pl-6 text-xs">
                      {r.can.length > 0 && <span><strong>Pode:</strong> {r.can.join("; ")}.</span>}
                      {r.cannot.length > 0 && <span><strong>Não pode:</strong> {r.cannot.join("; ")}.</span>}
                    </span>
                  )}
                </label>
              ))}
            </fieldset>
            <button type="submit" disabled={busy || !role} className="min-h-touch rounded-btn bg-accent px-4 font-medium text-[color:var(--on-accent)] disabled:opacity-60">{busy ? "Criando…" : "Criar convite"}</button>
          </form>
        )}
        {needStepUp && !done && <div className="mt-4"><MfaStepUp onDone={() => last.current && void send(last.current)} /></div>}
      </EntityDetailDrawer>
    </>
  );
}
