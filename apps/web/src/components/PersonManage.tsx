"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { EntityDetailDrawer } from "@/components/EntityDetailDrawer";
import { MfaStepUp } from "@/components/MfaStepUp";
import { SecretLink } from "@/components/SecretLink";
import { ROLE_CHANGE_ERROR } from "@/lib/roles";
import { TEAM_ERROR } from "@/lib/team";
import type { TeamMember, TeamRole } from "@/lib/types";

const MFA_ERROR: Record<string, string> = {
  invalid: "Senha ou código incorretos.", throttled: "Muitas tentativas. Aguarde 15 minutos e tente de novo.",
  other_workspaces: "Esta conta também pertence a outro provedor; só o suporte da plataforma pode redefinir a verificação.",
  admin_needs_mfa: "Ative a sua própria verificação em duas etapas (Conta › Segurança da conta) antes de redefinir a de outra pessoa.",
  not_found: "Esta pessoa não faz mais parte da equipe.", session: TEAM_ERROR.session, forbidden: TEAM_ERROR.forbidden, failed: TEAM_ERROR.failed,
};

/** O que muda ao trocar a função, em frases (a partir do que cada função pode e não pode). */
export function whatChanges(from: TeamRole | undefined, to: TeamRole | undefined): { gains: string[]; losses: string[] } {
  if (!from || !to) return { gains: [], losses: [] };
  return { gains: to.can.filter((c) => !from.can.includes(c)), losses: from.can.filter((c) => !to.can.includes(c)) };
}

type Act = () => Promise<void>;

/** Tudo sobre UMA pessoa em um painel só: função, senha, verificação em duas etapas e remoção. Cada ação é pequena e diz o que vai acontecer. */
export function PersonManage({ m, roles, canManage }: { m: TeamMember; roles: TeamRole[]; canManage: boolean }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [needStepUp, setNeedStepUp] = useState(false);
  const [newRole, setNewRole] = useState("");
  const [link, setLink] = useState<{ token: string } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const retry = useRef<Act | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const current = roles.find((r) => r.role === m.role);
  const options = roles.filter((r) => r.assignable_by_me && r.role !== m.role);
  const diff = whatChanges(current, roles.find((r) => r.role === newRole));
  const close = () => { setOpen(false); setError(null); setNeedStepUp(false); setLink(null); setNotice(null); setNewRole(""); trigger.current?.focus(); };

  async function guard(act: Act) {
    retry.current = act; setBusy(true); setError(null); setNotice(null);
    try { await act(); } catch { setError(TEAM_ERROR.failed); } finally { setBusy(false); }
  }
  async function post(url: string, body: unknown, ok: (j: Record<string, unknown>) => void, messages: Record<string, string> = TEAM_ERROR) {
    const res = await fetch(url, { method: "POST", headers: { "content-type": "application/json" }, cache: "no-store", body: JSON.stringify(body) });
    const j = (await res.json().catch(() => ({}))) as Record<string, unknown>;
    if (res.ok) { setNeedStepUp(false); ok(j); return; }
    if (j.error === "mfa_recent_required") { setNeedStepUp(true); return; }
    setError(messages[String(j.error ?? "failed")] ?? TEAM_ERROR[String(j.error ?? "failed")] ?? TEAM_ERROR.failed);
  }

  const changeRole = (fd: FormData) => guard(() => post(`/bff/members/${m.user_id}/role`, { role: newRole, reason: String(fd.get("reason") ?? "").trim() },
    () => { close(); router.refresh(); }, ROLE_CHANGE_ERROR));
  const resetLink = () => guard(() => post(`/bff/team/members/${m.user_id}`, { action: "reset" }, (j) => setLink({ token: String(j.token) })));
  const remove = (fd: FormData) => guard(() => post(`/bff/team/members/${m.user_id}`, { action: "remove", reason: String(fd.get("reason") ?? "").trim() }, () => { close(); router.refresh(); }));
  const mfaReset = (fd: FormData) => guard(() => post(`/bff/members/${m.user_id}/mfa-reset`, { password: fd.get("password"), code: fd.get("code") },
    () => { setNotice("Verificação em duas etapas redefinida. A pessoa cadastra de novo no próximo acesso."); router.refresh(); }, MFA_ERROR));

  const section = "grid gap-3 rounded-btn border border-line p-3";
  const input = "min-h-touch rounded-btn border border-line bg-bg px-3";
  const act = (fn: (fd: FormData) => Promise<void>) => (e: React.FormEvent<HTMLFormElement>) => { e.preventDefault(); const fd = new FormData(e.currentTarget); void fn(fd); };
  return (
    <>
      <button ref={trigger} type="button" onClick={() => setOpen(true)} aria-haspopup="dialog" data-testid="person-open" aria-label={`Gerenciar ${m.name}`}
        className="min-h-touch rounded-btn border border-line px-3 text-sm hover:bg-bg">Gerenciar</button>
      <EntityDetailDrawer open={open} onClose={close} title={m.name}>
        <div className="grid gap-4 text-sm" data-testid="person-panel">
          <div><div className="font-medium">{m.role_label}</div><div className="text-muted">{m.email}</div><div className="mt-1 text-muted">{m.role_summary}</div></div>
          {error && <p role="alert" data-testid="person-error" className="text-danger">{error}</p>}
          {notice && <p role="status" data-testid="person-notice">{notice}</p>}
          {needStepUp && <MfaStepUp onDone={() => retry.current && void guard(retry.current)} />}
          {!canManage ? <p className="text-muted">Seu papel só consulta a equipe.</p> : (
            <>
              {m.can_change_role && (
                <details className={section} open>
                  <summary className="cursor-pointer font-medium">Mudar a função</summary>
                  <form onSubmit={act(changeRole)} className="mt-2 grid gap-3" data-testid="role-form">
                    <label className="grid gap-1">Nova função
                      <select required value={newRole} onChange={(e) => setNewRole(e.target.value)} className={input}>
                        <option value="" disabled>Escolha…</option>
                        {options.map((r) => <option key={r.role} value={r.role}>{r.label}</option>)}
                      </select>
                    </label>
                    {newRole && (
                      <div role="note" className="rounded-btn bg-bg p-3" data-testid="role-diff">
                        <p className="font-medium">O que muda</p>
                        <ul className="mt-1 list-disc pl-5 text-muted">
                          {diff.gains.map((g) => <li key={g}>Passa a poder: {g.toLowerCase()}</li>)}
                          {diff.losses.map((g) => <li key={g}>Deixa de poder: {g.toLowerCase()}</li>)}
                          {diff.gains.length + diff.losses.length === 0 && <li>As capacidades principais são as mesmas.</li>}
                          <li>{m.name} será desconectada de todos os provedores da conta e entra de novo com a nova função.</li>
                        </ul>
                      </div>
                    )}
                    <label className="grid gap-1">Motivo (3 a 200 caracteres)
                      <textarea name="reason" required minLength={3} maxLength={200} rows={2} className="rounded-btn border border-line bg-bg p-3" />
                    </label>
                    <button type="submit" disabled={busy || !newRole} className="min-h-touch rounded-btn bg-accent px-4 font-medium text-[color:var(--on-accent)] disabled:opacity-60">Mudar a função</button>
                  </form>
                </details>
              )}
              {m.can_reset_password && (
                <details className={section}>
                  <summary className="cursor-pointer font-medium">Redefinir a senha</summary>
                  <div className="mt-2 grid gap-3">
                    <p className="text-muted">Você gera um link e envia à pessoa. Ela escolhe a nova senha; você nunca vê a senha. As sessões atuais dela terminam quando ela trocar.</p>
                    {link ? <SecretLink url={`${window.location.origin}/convite/${link.token}`} validity="24 horas" title="Link para trocar a senha" /> : (
                      <button type="button" disabled={busy} onClick={() => void resetLink()} data-testid="reset-link"
                        className="min-h-touch rounded-btn border border-line px-4 hover:bg-bg disabled:opacity-60">Gerar link para trocar a senha</button>
                    )}
                  </div>
                </details>
              )}
              {m.mfa_enabled && !m.is_self && (
                <details className={section}>
                  <summary className="cursor-pointer font-medium">Redefinir a verificação em duas etapas</summary>
                  <form onSubmit={act(mfaReset)} className="mt-2 grid gap-3" data-testid="mfa-form">
                    <p className="text-muted">Apaga a verificação de {m.name} e encerra as sessões dela. Confirme com a <strong>sua</strong> senha e o <strong>seu</strong> código.</p>
                    <label className="grid gap-1">Sua senha<input name="password" type="password" required autoComplete="current-password" className={input} /></label>
                    <label className="grid gap-1">Seu código do autenticador ou de recuperação<input name="code" required autoComplete="one-time-code" className={`${input} tabular-nums`} /></label>
                    <button type="submit" disabled={busy} className="min-h-touch rounded-btn border border-danger px-4 text-danger disabled:opacity-60">Redefinir verificação</button>
                  </form>
                </details>
              )}
              {m.can_remove && (
                <details className={`${section} border-danger`}>
                  <summary className="cursor-pointer font-medium text-danger">Remover da equipe</summary>
                  <form onSubmit={act(remove)} className="mt-2 grid gap-3" data-testid="remove-form">
                    <p className="text-muted">{m.name} perde o acesso a este provedor na hora. A conta continua existindo se ela fizer parte de outro provedor. A ação fica registrada com o seu nome.</p>
                    <label className="grid gap-1">Motivo (3 a 200 caracteres)<textarea name="reason" required minLength={3} maxLength={200} rows={2} className="rounded-btn border border-line bg-bg p-3" /></label>
                    <button type="submit" disabled={busy} className="min-h-touch rounded-btn bg-danger px-4 font-medium text-[color:var(--on-accent)] disabled:opacity-60" data-testid="remove-submit">Remover {m.name}</button>
                  </form>
                </details>
              )}
            </>
          )}
        </div>
      </EntityDetailDrawer>
    </>
  );
}
