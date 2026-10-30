"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { EntityDetailDrawer } from "@/components/EntityDetailDrawer";
import { MfaStepUp } from "@/components/MfaStepUp";
import { SecretLink } from "@/components/SecretLink";
import { TEAM_ERROR, inviteLink } from "@/lib/team";

/** Convite pendente: gerar um novo link (o antigo deixa de valer) ou cancelar. */
export function InviteActions({ id, email }: { id: string; email: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [needStepUp, setNeedStepUp] = useState(false);
  const [token, setToken] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const pending = useRef<"renew" | "cancel">("renew");
  const trigger = useRef<HTMLButtonElement>(null);
  const close = () => { setOpen(false); setNeedStepUp(false); setError(null); if (token) router.refresh(); setToken(null); trigger.current?.focus(); };

  async function run(action: "renew" | "cancel") {
    pending.current = action; setBusy(true); setError(null);
    try {
      const res = await fetch(`/bff/team/invites/${id}`, { method: "POST", headers: { "content-type": "application/json" }, cache: "no-store", body: JSON.stringify({ action }) });
      const j = (await res.json().catch(() => ({}))) as { error?: string; token?: string };
      if (res.ok) {
        setNeedStepUp(false);
        if (action === "renew" && j.token) { setToken(j.token); setOpen(true); } else router.refresh();
        return;
      }
      if (j.error === "mfa_recent_required") { setNeedStepUp(true); setOpen(true); return; }
      setError(TEAM_ERROR[j.error ?? "failed"] ?? TEAM_ERROR.failed); setOpen(true);
    } catch { setError(TEAM_ERROR.failed); setOpen(true); } finally { setBusy(false); }
  }

  return (
    <div className="flex flex-wrap gap-2">
      <button ref={trigger} type="button" disabled={busy} onClick={() => void run("renew")} data-testid="invite-renew" aria-label={`Gerar novo link para ${email}`}
        className="min-h-touch rounded-btn border border-line px-3 text-sm hover:bg-bg disabled:opacity-60">Gerar novo link</button>
      <button type="button" disabled={busy} onClick={() => void run("cancel")} data-testid="invite-cancel" aria-label={`Cancelar o convite de ${email}`}
        className="min-h-touch rounded-btn border border-line px-3 text-sm text-danger hover:bg-bg disabled:opacity-60">Cancelar convite</button>
      <EntityDetailDrawer open={open} onClose={close} title={token ? "Novo link de convite" : "Convite"}>
        <div className="grid gap-4 text-sm">
          {error && <p role="alert" className="text-danger">{error}</p>}
          {token && <SecretLink url={inviteLink(window.location.origin, token)} validity="72 horas" title={`Novo link para ${email}`} />}
          {needStepUp && <MfaStepUp onDone={() => void run(pending.current)} />}
          <button type="button" onClick={close} className="min-h-touch rounded-btn border border-line px-4">Fechar</button>
        </div>
      </EntityDetailDrawer>
    </div>
  );
}
