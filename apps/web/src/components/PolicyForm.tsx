"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { MfaStepUp } from "@/components/MfaStepUp";
import { affected, roleName, sameSet } from "@/lib/orgSecurity";
import { TEAM_ERROR } from "@/lib/team";
import type { SecurityPolicy } from "@/lib/types";

/** Segurança da organização (ADR-0049 D1): quais funções precisam de verificação em duas etapas. Só APERTA o que o ambiente já exige; nunca afrouxa. */
export function PolicyForm({ policy }: { policy: SecurityPolicy }) {
  const router = useRouter();
  const [chosen, setChosen] = useState<string[]>(policy.organization);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [needStepUp, setNeedStepUp] = useState(false);
  const last = useRef<string[]>([]);
  const dirty = !sameSet(chosen, policy.organization);
  const n = affected(policy, chosen);

  async function save(roles: string[]) {
    last.current = roles; setBusy(true); setError(null); setDone(null);
    try {
      const res = await fetch("/bff/politica", { method: "PUT", headers: { "content-type": "application/json" }, cache: "no-store", body: JSON.stringify({ mfa_required_roles: roles }) });
      const j = (await res.json().catch(() => ({}))) as { error?: string; changed?: boolean };
      if (res.ok) { setNeedStepUp(false); setConfirm(false); setDone(j.changed ? "Política salva. Quem ainda não tem a verificação será levado a cadastrá-la no próximo acesso." : "Nada mudou."); router.refresh(); return; }
      if (j.error === "mfa_recent_required") { setNeedStepUp(true); return; }
      setError(TEAM_ERROR[j.error ?? "failed"] ?? TEAM_ERROR.failed);
    } catch { setError(TEAM_ERROR.failed); } finally { setBusy(false); }
  }

  return (
    <form onSubmit={(e) => { e.preventDefault(); if (dirty) setConfirm(true); }} className="grid gap-5 text-sm" data-testid="policy-form">
      {!policy.mfa_available && <p role="alert" data-testid="policy-no-mfa" className="panel border-warn p-3">Este servidor ainda não consegue cadastrar a verificação em duas etapas; por isso exigi-la de mais funções está bloqueado.</p>}
      <fieldset className="grid gap-2" disabled={!policy.can_edit || busy}>
        <legend className="mb-1 font-medium">Quem precisa da verificação em duas etapas</legend>
        {policy.selectable.map((r) => {
          const locked = policy.floor.includes(r);
          return (
            <label key={r} className="flex min-h-touch items-start gap-2" data-testid={`policy-role-${r}`}>
              <input type="checkbox" className="mt-1 size-4" checked={locked || chosen.includes(r)} disabled={locked} onChange={(e) => setChosen(e.target.checked ? [...chosen, r] : chosen.filter((x) => x !== r))} />
              <span>{roleName(r)}{locked && <span className="ml-2 rounded-btn border border-line px-2 text-xs text-muted">exigido pela plataforma</span>}
                {(policy.members_without_mfa[r] ?? 0) > 0 && <span className="block text-xs text-muted">{policy.members_without_mfa[r]} {policy.members_without_mfa[r] === 1 ? "pessoa ainda não ativou" : "pessoas ainda não ativaram"}</span>}</span>
            </label>
          );
        })}
      </fieldset>
      <p className="text-muted">Você só pode <strong>acrescentar</strong> funções: o que a plataforma já exige (travado acima) não dá para tirar.</p>
      {!policy.can_edit && <p className="text-muted" data-testid="policy-readonly">Só um Administrador do provedor muda esta política.</p>}
      {error && <p role="alert" data-testid="policy-error" className="text-danger">{error}</p>}
      {done && <p role="status" data-testid="policy-done">{done}</p>}
      {needStepUp && <MfaStepUp onDone={() => void save(last.current)} />}
      {confirm && (
        <div role="alertdialog" aria-labelledby="pc-title" className="panel grid gap-3 border-warn p-4" data-testid="policy-confirm">
          <p id="pc-title" className="font-medium">Confirmar a nova política?</p>
          <p>{n === 0 ? "Todo mundo dessas funções já tem a verificação ativa." : `${n} ${n === 1 ? "pessoa será levada" : "pessoas serão levadas"} a cadastrar a verificação em duas etapas no próximo acesso; até lá só conseguem abrir a tela de segurança da conta.`}</p>
          <div className="flex flex-wrap gap-2">
            <button type="button" disabled={busy} onClick={() => void save(chosen)} data-testid="policy-confirm-yes" className="min-h-touch rounded-btn bg-accent px-4 font-medium text-[color:var(--on-accent)] disabled:opacity-60">Confirmar</button>
            <button type="button" onClick={() => setConfirm(false)} className="min-h-touch rounded-btn border border-line px-4">Voltar</button>
          </div>
        </div>
      )}
      {policy.can_edit && !confirm && <button type="submit" disabled={busy || !dirty || (!policy.mfa_available && chosen.length > 0)} data-testid="policy-save" className="min-h-touch w-fit rounded-btn bg-accent px-4 font-medium text-[color:var(--on-accent)] disabled:opacity-60">Salvar política</button>}
    </form>
  );
}
