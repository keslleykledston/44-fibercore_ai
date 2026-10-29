"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { EntityDetailDrawer } from "@/components/EntityDetailDrawer";

const MSG: Record<string, string> = {
  invalid: "Senha ou código incorretos.",
  session: "Sua sessão expirou. Recarregue a página e entre de novo.",
  throttled: "Muitas tentativas. Aguarde 15 minutos e tente de novo.",
  other_workspaces: "Esta conta também pertence a outros workspaces; o MFA é da conta inteira e só o suporte da plataforma pode redefini-lo.",
  admin_needs_mfa: "Ative o seu próprio MFA (Conta › Segurança da conta) antes de redefinir o de outra pessoa.",
  self: "Para o seu próprio MFA use Conta › Segurança da conta.",
  not_found: "Esta pessoa não faz mais parte do workspace.",
  forbidden: "Seu papel não permite esta ação.",
  conflict: "Não foi possível redefinir agora.",
  unavailable: "Serviço indisponível. Tente em instantes.",
  failed: "Falha inesperada. Tente em instantes.",
};

/** Redefinição de MFA de OUTRA pessoa: confirmação com senha + segundo fator do próprio administrador. */
export function MemberMfaReset({ userId, name }: { userId: string; name: string }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const router = useRouter();
  const close = () => { setOpen(false); setError(null); trigger.current?.focus(); };

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    setBusy(true); setError(null);
    try {
      const res = await fetch(`/bff/members/${userId}/mfa-reset`, {
        method: "POST", headers: { "content-type": "application/json" }, cache: "no-store",
        body: JSON.stringify({ password: fd.get("password"), code: fd.get("code") }),
      });
      const j = await res.json().catch(() => ({}));
      if (res.ok) { setOpen(false); router.refresh(); return; }
      setError(MSG[(j as { error?: string }).error ?? "failed"] ?? MSG.failed);
    } catch { setError(MSG.failed); } finally { setBusy(false); }
  }

  return (
    <>
      <button ref={trigger} type="button" data-testid="mfa-reset-open" aria-haspopup="dialog" onClick={() => setOpen(true)}
        className="min-h-touch rounded-btn border border-line px-3 text-sm text-danger hover:bg-bg">Redefinir MFA</button>
      <EntityDetailDrawer open={open} onClose={close} title={`Redefinir MFA de ${name}`}>
        <form onSubmit={submit} className="grid gap-4 text-sm" data-testid="mfa-reset-form">
          <div role="note" className="rounded-btn border border-line bg-bg p-3">
            <p className="font-medium">O que acontece</p>
            <ul className="mt-1 list-disc pl-5 text-muted">
              <li>O MFA e os códigos de recuperação de {name} são apagados.</li>
              <li>As sessões abertas de {name} são encerradas.</li>
              <li>Até cadastrar o MFA de novo, a conta fica só com senha — a menos que o seu perfil exija MFA, caso em que o acesso fica bloqueado até o novo cadastro.</li>
              <li>A ação fica registrada na auditoria, com o seu nome.</li>
            </ul>
          </div>
          {error && <p role="alert" data-testid="mfa-reset-error" className="text-danger">{error}</p>}
          <label className="grid gap-1">Sua senha
            <input name="password" type="password" required autoComplete="current-password" className="min-h-touch rounded-btn border border-line bg-bg px-3" />
          </label>
          <label className="grid gap-1">Seu código do autenticador ou de recuperação
            <input name="code" required autoComplete="one-time-code" className="min-h-touch rounded-btn border border-line bg-bg px-3 tabular-nums" />
          </label>
          <button type="submit" disabled={busy} className="min-h-touch rounded-btn bg-danger px-4 font-medium text-white disabled:opacity-60">{busy ? "Redefinindo…" : "Redefinir MFA"}</button>
        </form>
      </EntityDetailDrawer>
    </>
  );
}
